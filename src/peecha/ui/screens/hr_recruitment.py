"""R367: جذب و استخدام — فرصت‌های شغلی، متقاضیان، مراحل استخدام با مصاحبه و گزارش."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import QTime, Qt
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget,
    QTimeEdit, QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services import hr as hr_service
from peecha.services import hr_recruitment as rec
from peecha.ui import report_export, theme
from peecha.ui.screens.fixed_assets import P, combo, company_id, dec, fill, selected_data, set_combo, table, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec, JalaliDateEdit, build_page_header


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


def _codes(box: QComboBox, mapping: dict[str, str]) -> QComboBox:
    for code, label in mapping.items():
        box.addItem(label, code)
    return box


def _amount(value) -> str:
    return P(f"{value.normalize():f}") if value is not None else ""


class HrRecruitmentScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.openings: list = []
        self.candidates: list = []
        self.applications: list = []
        self.interviews: list = []
        self._opening_id: int | None = None
        self._candidate_id: int | None = None
        self.ask_text = None  # برای آزمون: تابعی که متن پرسیده‌شده (دلیل رد یا کد پرسنلی) را برمی‌گرداند
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "جذب و استخدام", "فرصت شغلی روی پست سازمانی، ثبت متقاضی، پیگیری مراحل از دریافت درخواست تا پیشنهاد همکاری، مصاحبه با "
            "امتیاز و استخدام که پروندهٔ پرسنلی را با همان پست و حقوق پیشنهادی می‌سازد."))
        self.tabs = QTabWidget()
        self.tabs.addTab(self._openings_tab(), "فرصت‌های شغلی")
        self.tabs.addTab(self._candidates_tab(), "متقاضیان")
        self.pipeline_tab = self._pipeline_tab()
        self.tabs.addTab(self.pipeline_tab, "مراحل استخدام")
        self.tabs.addTab(self._report_tab(), "گزارش جذب")
        layout.addWidget(self.tabs, 1)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def _status(self, text: str, ok: bool) -> None:
        theme.set_status_label(self.status_label, text, ok=ok)

    def _ask(self, title: str, prompt: str) -> str | None:
        if self.ask_text is not None:
            return self.ask_text()
        text, ok = QInputDialog.getText(self, title, prompt)
        return text if ok else None

    # --- فرصت‌ها ------------------------------------------------------------------------------------------------------
    def _openings_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.opening_table = table(["کد", "عنوان", "پست", "نیرو", "استخدام‌شده", "درخواست‌ها", "وضعیت", "شروع", "مهلت", "مدیر استخدام"])
        self.opening_table.itemSelectionChanged.connect(self._load_opening)
        v.addWidget(self.opening_table, 1)
        self.op_code, self.op_title = QLineEdit(), QLineEdit()
        self.op_position = combo([], "—")
        self.op_headcount = QSpinBox()
        self.op_headcount.setRange(1, 999)
        self.op_status = _codes(QComboBox(), rec.OPENING_STATUSES)
        self.op_opened, self.op_close = JalaliDateEdit(), JalaliDateEdit(allow_empty=True)
        self.op_min, self.op_max = QLineEdit(), QLineEdit()
        self.op_manager = combo([], "—")
        self.op_desc, self.op_req = QLineEdit(), QLineEdit()
        v.addWidget(FieldGrid([
            FieldSpec("op_code", "کد", self.op_code, span=1), FieldSpec("op_title", "عنوان شغل", self.op_title, span=1),
            FieldSpec("op_position", "پست سازمانی", self.op_position, span=1), FieldSpec("op_headcount", "تعداد نیرو", self.op_headcount, span=1),
            FieldSpec("op_status", "وضعیت", self.op_status, span=1), FieldSpec("op_manager", "مدیر استخدام", self.op_manager, span=1),
            FieldSpec("op_opened", "تاریخ شروع جذب", self.op_opened, span=1), FieldSpec("op_close", "مهلت جذب", self.op_close, span=1),
            FieldSpec("op_min", "کف حقوق", self.op_min, span=1), FieldSpec("op_max", "سقف حقوق", self.op_max, span=1),
            FieldSpec("op_desc", "شرح شغل", self.op_desc, span=2), FieldSpec("op_req", "شرایط احراز", self.op_req, span=3)]))
        v.addLayout(_bar(("ذخیرهٔ فرصت شغلی", "💾", "primary", self.save_opening), ("فرصت جدید", "🆕", "", self.new_opening),
                         ("به‌روزرسانی", "🔄", "", self.refresh)))
        return w

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        employees = [(f"{e.employee_code} — {e.full_name}", e.employee_id) for e in hr_service.list_employees(cid) if e.status == "ACTIVE"]
        positions = [(f"{p.code} — {p.title} ({p.org_unit_name})", p.position_id) for p in hr_service.list_positions(cid)]
        for box, items in ((self.op_position, positions), (self.op_manager, employees), (self.iv_interviewer, employees)):
            current = box.currentData()
            box.clear()
            box.addItem("—", None)
            for label, data in items:
                box.addItem(P(label), data)
            set_combo(box, current)
        self.openings = rec.list_openings(cid)
        fill(self.opening_table, [[o.code, o.title, o.position_title, o.headcount, o.hired, o.applications, o.status_label, o.opened_on,
                                   o.close_by or "—", o.hiring_manager or "—"] for o in self.openings], [o.opening_id for o in self.openings])
        self.refresh_candidates()
        for box, items in ((self.app_opening, [(o.label, o.opening_id) for o in self.openings if o.status_code == "OPEN"]),
                           (self.filter_opening, [(o.label, o.opening_id) for o in self.openings]),
                           (self.app_candidate, [(f"{c.full_name} {c.national_id}".strip(), c.candidate_id) for c in self.candidates])):
            current = box.currentData()
            box.blockSignals(True)
            box.clear()
            box.addItem("— همه —" if box is self.filter_opening else "—", None)
            for label, data in items:
                box.addItem(P(label), data)
            set_combo(box, current)
            box.blockSignals(False)
        self.refresh_pipeline()
        self.refresh_report()

    def _load_opening(self) -> None:
        o = next((x for x in self.openings if x.opening_id == selected_data(self.opening_table)), None)
        if o is None:
            return
        self._opening_id = o.opening_id
        self.op_code.setText(o.code)
        self.op_title.setText(o.title)
        set_combo(self.op_position, o.position_id)
        self.op_headcount.setValue(o.headcount)
        self.op_status.setCurrentIndex(self.op_status.findData(o.status_code))
        set_combo(self.op_manager, o.hiring_manager_employee_id)
        self.op_opened.setDate(o.opened_on)
        self.op_close.setDate(o.close_by)
        self.op_min.setText(_amount(o.salary_min))
        self.op_max.setText(_amount(o.salary_max))
        self.op_desc.setText(o.description)
        self.op_req.setText(o.requirements)

    def new_opening(self) -> None:
        self._opening_id = None
        self.opening_table.clearSelection()
        for f in (self.op_code, self.op_title, self.op_min, self.op_max, self.op_desc, self.op_req):
            f.clear()
        self.op_headcount.setValue(1)
        self.op_status.setCurrentIndex(0)
        self.op_opened.setDate(datetime.date.today())
        self.op_close.setDate(None)

    def save_opening(self) -> int | None:
        if self.op_position.currentData() is None:
            self._status("پست سازمانی را انتخاب کنید.", False)
            return None
        try:
            fields = rec.OpeningFields(
                self.op_code.text(), self.op_title.text(), self.op_position.currentData(), self.op_opened.date(),
                self.op_headcount.value(), self.op_status.currentData(), self.op_close.date(),
                dec(self.op_min.text()) if self.op_min.text().strip() else None, dec(self.op_max.text()) if self.op_max.text().strip() else None,
                self.op_manager.currentData(), self.op_desc.text(), self.op_req.text())
            opening_id = rec.save_opening(company_id(), user_id(), fields, self._opening_id)
        except (ValueError, decimal.InvalidOperation) as exc:
            self._status(str(exc) if isinstance(exc, ValueError) else "مبلغ حقوق نامعتبر است.", False)
            return None
        self.new_opening()
        self.refresh()
        self._status("فرصت شغلی ذخیره شد.", True)
        return opening_id

    # --- متقاضیان -----------------------------------------------------------------------------------------------------
    def _candidates_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        search = QHBoxLayout()
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("جست‌وجو با نام، کد ملی یا موبایل")
        self.search_field.returnPressed.connect(self.refresh_candidates)
        search.addWidget(self.search_field, 1)
        find = _btn("جست‌وجو", "🔎")
        find.clicked.connect(self.refresh_candidates)
        search.addWidget(find)
        v.addLayout(search)
        self.candidate_table = table(["نام", "کد ملی", "موبایل", "تحصیلات", "سابقه (سال)", "منبع", "درخواست‌ها"])
        self.candidate_table.itemSelectionChanged.connect(self._load_candidate)
        v.addWidget(self.candidate_table, 1)
        self.c_first, self.c_last, self.c_national, self.c_mobile, self.c_email, self.c_edu, self.c_notes = (QLineEdit() for _ in range(7))
        self.c_exp = QDoubleSpinBox()
        self.c_exp.setRange(0, 60)
        self.c_exp.setDecimals(1)
        self.c_source = _codes(QComboBox(), rec.SOURCES)
        v.addWidget(FieldGrid([
            FieldSpec("c_first", "نام", self.c_first, span=1), FieldSpec("c_last", "نام خانوادگی", self.c_last, span=1),
            FieldSpec("c_national", "کد ملی", self.c_national, span=1), FieldSpec("c_mobile", "موبایل", self.c_mobile, span=1),
            FieldSpec("c_email", "ایمیل", self.c_email, span=1), FieldSpec("c_source", "منبع آشنایی", self.c_source, span=1),
            FieldSpec("c_edu", "تحصیلات", self.c_edu, span=1), FieldSpec("c_exp", "سابقهٔ کار (سال)", self.c_exp, span=1),
            FieldSpec("c_notes", "یادداشت", self.c_notes, span=1)]))
        v.addLayout(_bar(("ذخیرهٔ متقاضی", "💾", "primary", self.save_candidate), ("متقاضی جدید", "🆕", "", self.new_candidate)))
        return w

    def refresh_candidates(self) -> None:
        if company_id() is None:
            return
        self.candidates = rec.list_candidates(company_id(), self.search_field.text())
        fill(self.candidate_table, [[c.full_name, c.national_id or "—", c.mobile or "—", c.education or "—",
                                     _amount(c.experience_years) or "—", c.source_label, c.applications] for c in self.candidates],
             [c.candidate_id for c in self.candidates])

    def _load_candidate(self) -> None:
        c = next((x for x in self.candidates if x.candidate_id == selected_data(self.candidate_table)), None)
        if c is None:
            return
        self._candidate_id = c.candidate_id
        for field, value in ((self.c_first, c.first_name), (self.c_last, c.last_name), (self.c_national, P(c.national_id)),
                             (self.c_mobile, P(c.mobile)), (self.c_email, c.email), (self.c_edu, c.education), (self.c_notes, c.notes)):
            field.setText(value)
        self.c_exp.setValue(float(c.experience_years or 0))
        self.c_source.setCurrentIndex(self.c_source.findData(c.source_code))

    def new_candidate(self) -> None:
        self._candidate_id = None
        self.candidate_table.clearSelection()
        for f in (self.c_first, self.c_last, self.c_national, self.c_mobile, self.c_email, self.c_edu, self.c_notes):
            f.clear()
        self.c_exp.setValue(0)
        self.c_source.setCurrentIndex(0)

    def save_candidate(self) -> int | None:
        try:
            candidate_id = rec.save_candidate(company_id(), rec.CandidateFields(
                self.c_first.text(), self.c_last.text(), self.c_national.text(), self.c_mobile.text(), self.c_email.text(),
                self.c_edu.text(), decimal.Decimal(str(self.c_exp.value())), self.c_source.currentData(), self.c_notes.text()),
                self._candidate_id)
        except ValueError as exc:
            self._status(str(exc), False)
            return None
        self.new_candidate()
        self.refresh()
        self._status("متقاضی ذخیره شد.", True)
        return candidate_id

    # --- مراحل استخدام ------------------------------------------------------------------------------------------------
    def _pipeline_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        top = QHBoxLayout()
        self.filter_opening = combo([], "— همه —")
        self.filter_opening.currentIndexChanged.connect(self.refresh_pipeline)
        self.app_opening, self.app_candidate = combo([], "—"), combo([], "—")
        top.addWidget(FieldGrid([FieldSpec("pl_filter", "نمایش فرصت", self.filter_opening, span=1),
                                 FieldSpec("pl_opening", "فرصت شغلی", self.app_opening, span=1),
                                 FieldSpec("pl_candidate", "متقاضی", self.app_candidate, span=1)]), 1)
        add = _btn("ثبت درخواست متقاضی برای فرصت", "➕", "primary")
        add.clicked.connect(self.add_application)
        top.addWidget(add)
        v.addLayout(top)
        self.app_table = table(["متقاضی", "فرصت شغلی", "مرحله", "تاریخ درخواست", "امتیاز مصاحبه", "مصاحبه‌ها", "حقوق پیشنهادی",
                                "شروع همکاری", "توضیح"])
        self.app_table.itemSelectionChanged.connect(self._load_application)
        v.addWidget(self.app_table, 1)
        self.offer_salary, self.offer_start = QLineEdit(), JalaliDateEdit()
        offer = QHBoxLayout()
        offer.addWidget(FieldGrid([FieldSpec("pl_salary", "حقوق پیشنهادی", self.offer_salary, span=1),
                                   FieldSpec("pl_start", "تاریخ شروع همکاری", self.offer_start, span=1)], columns=2), 1)
        v.addLayout(offer)
        v.addLayout(_bar(("مرحلهٔ بعد (بررسی اولیه، مصاحبه)", "⏭️", "primary", self.advance),
                         ("پیشنهاد همکاری با حقوق و تاریخ شروع", "💼", "", self.offer),
                         ("استخدام و ساخت پروندهٔ پرسنلی", "✅", "", self.hire),
                         ("رد متقاضی", "❌", "danger", self.reject), ("انصراف متقاضی", "↩️", "", self.withdraw),
                         ("بازگشایی درخواست", "🔁", "", self.reopen)))
        self.history_label = QLabel("")
        self.history_label.setWordWrap(True)
        self.history_label.setObjectName("mutedLabel")
        v.addWidget(self.history_label)
        self.iv_day = JalaliDateEdit()
        self.iv_time = QTimeEdit(QTime(10, 0))
        self.iv_time.setDisplayFormat("HH:mm")
        self.iv_interviewer = combo([], "—")
        self.iv_mode = _codes(QComboBox(), rec.MODES)
        self.iv_score = QSpinBox()
        self.iv_score.setRange(1, 5)
        self.iv_rec = _codes(QComboBox(), rec.RECOMMENDATIONS)
        self.iv_notes = QLineEdit()
        iv = QHBoxLayout()
        iv.addWidget(FieldGrid([FieldSpec("iv_day", "روز مصاحبه", self.iv_day, span=1), FieldSpec("iv_time", "ساعت", self.iv_time, span=1),
                                FieldSpec("iv_who", "مصاحبه‌گر", self.iv_interviewer, span=1), FieldSpec("iv_mode", "نوع", self.iv_mode, span=1),
                                FieldSpec("iv_score", "امتیاز (۱ تا ۵)", self.iv_score, span=1),
                                FieldSpec("iv_rec", "پیشنهاد", self.iv_rec, span=1), FieldSpec("iv_notes", "یادداشت", self.iv_notes, span=1)]), 1)
        v.addLayout(iv)
        v.addLayout(_bar(("برنامه‌ریزی مصاحبه", "📅", "primary", self.schedule_interview),
                         ("ثبت نتیجهٔ مصاحبهٔ انتخاب‌شده", "📝", "", self.record_interview),
                         ("لغو مصاحبهٔ انتخاب‌شده", "🚫", "danger", self.cancel_interview)))
        self.interview_table = table(["زمان", "مصاحبه‌گر", "نوع", "وضعیت", "امتیاز", "پیشنهاد", "یادداشت"])
        self.interview_table.setMaximumHeight(150)
        v.addWidget(self.interview_table)
        return w

    def refresh_pipeline(self) -> None:
        if company_id() is None:
            return
        self.applications = rec.list_applications(company_id(), self.filter_opening.currentData())
        fill(self.app_table, [[a.candidate_name, a.opening_label, a.stage_label, a.applied_on, P(a.rating) if a.rating is not None else "—",
                               a.interviews, a.offer_salary if a.offer_salary is not None else "—", a.offer_start_date or "—",
                               a.decision_note] for a in self.applications], [a.application_id for a in self.applications])
        self.interview_table.setRowCount(0)
        self.history_label.setText("")

    def _selected_application(self):
        a = next((x for x in self.applications if x.application_id == selected_data(self.app_table)), None)
        if a is None:
            self._status("یک درخواست را از جدول انتخاب کنید.", False)
        return a

    def _load_application(self) -> None:
        a = next((x for x in self.applications if x.application_id == selected_data(self.app_table)), None)
        if a is None:
            return
        self.offer_salary.setText(_amount(a.offer_salary))
        if a.offer_start_date:
            self.offer_start.setDate(a.offer_start_date)
        steps = rec.history(company_id(), a.application_id)
        self.history_label.setText("سابقه: " + " ← ".join(f"{s[2]} ({numerals.format_jalali_date(s[0].date())})" for s in steps))
        self.interviews = rec.list_interviews(company_id(), a.application_id)
        fill(self.interview_table, [[numerals.format_jalali_datetime(i.scheduled_at), i.interviewer or "—", rec.MODES[i.mode_code],
                                     i.status_label, i.score or "—", rec.RECOMMENDATIONS.get(i.recommendation_code, "—"), i.notes]
                                    for i in self.interviews], [i.interview_id for i in self.interviews])

    def _run(self, fn, done: str):
        a = self._selected_application()
        if a is None:
            return None
        try:
            result = fn(a)
        except (ValueError, decimal.InvalidOperation) as exc:
            self._status(str(exc) if isinstance(exc, ValueError) else "مبلغ نامعتبر است.", False)
            return None
        selected = a.application_id
        self.refresh()
        row = next((i for i, x in enumerate(self.applications) if x.application_id == selected), None)
        if row is not None:
            self.app_table.setCurrentCell(row, 0)
            self._load_application()
        self._status(done, True)
        return result if result is not None else True

    def add_application(self) -> int | None:
        if self.app_opening.currentData() is None or self.app_candidate.currentData() is None:
            self._status("فرصت شغلی و متقاضی را انتخاب کنید.", False)
            return None
        try:
            application_id = rec.apply(company_id(), user_id(), self.app_opening.currentData(), self.app_candidate.currentData())
        except ValueError as exc:
            self._status(str(exc), False)
            return None
        self.refresh()
        self._status("درخواست ثبت شد.", True)
        return application_id

    def advance(self):
        return self._run(lambda a: rec.advance(company_id(), user_id(), a.application_id), "درخواست به مرحلهٔ بعد رفت.")

    def offer(self):
        return self._run(lambda a: rec.make_offer(company_id(), user_id(), a.application_id, dec(self.offer_salary.text()),
                                                  self.offer_start.date()), "پیشنهاد همکاری ثبت شد.")

    def hire(self):
        a = self._selected_application()
        if a is None:
            return None
        code = self._ask("استخدام", "کد پرسنلی کارمند جدید:")
        if not code:
            return None
        return self._run(lambda a: rec.hire(company_id(), user_id(), a.application_id, code),
                         "متقاضی استخدام شد و پروندهٔ پرسنلی‌اش ساخته شد.")

    def reject(self):
        a = self._selected_application()
        if a is None:
            return None
        reason = self._ask("رد متقاضی", "دلیل رد:")
        if reason is None:
            return None
        return self._run(lambda a: rec.close(company_id(), user_id(), a.application_id, "REJECTED", reason), "متقاضی رد شد.")

    def withdraw(self):
        return self._run(lambda a: rec.close(company_id(), user_id(), a.application_id, "WITHDRAWN"), "انصراف متقاضی ثبت شد.")

    def reopen(self):
        return self._run(lambda a: rec.reopen(company_id(), user_id(), a.application_id), "درخواست دوباره باز شد.")

    def schedule_interview(self):
        when = datetime.datetime.combine(self.iv_day.date(), self.iv_time.time().toPython()).astimezone()
        return self._run(lambda a: rec.schedule_interview(company_id(), user_id(), a.application_id, when,
                                                          self.iv_interviewer.currentData(), self.iv_mode.currentData()),
                         "مصاحبه برنامه‌ریزی شد.")

    def _interview_id(self):
        iid = selected_data(self.interview_table)
        if iid is None:
            self._status("یک مصاحبه را از جدول مصاحبه‌ها انتخاب کنید.", False)
        return iid

    def record_interview(self):
        iid = self._interview_id()
        if iid is None:
            return None
        return self._run(lambda a: rec.record_interview(company_id(), iid, self.iv_score.value(), self.iv_rec.currentData(),
                                                        self.iv_notes.text()), "نتیجهٔ مصاحبه ثبت شد.")

    def cancel_interview(self):
        iid = self._interview_id()
        if iid is None:
            return None
        return self._run(lambda a: rec.cancel_interview(company_id(), iid), "مصاحبه لغو شد.")

    def open_interviews(self) -> None:
        self.tabs.setCurrentWidget(self.pipeline_tab)

    # --- گزارش ------------------------------------------------------------------------------------------------------
    def _report_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.report_table = table(["فرصت شغلی", "وضعیت", "نیرو"] + [rec.STAGES[s] for s in rec.STAGES] + ["میانگین روز تا استخدام"])
        v.addWidget(self.report_table, 1)
        v.addWidget(QLabel("اثربخشی منابع جذب"))
        self.source_table = table(["منبع", "درخواست‌ها", "استخدام‌شده"])
        self.source_table.setMaximumHeight(170)
        v.addWidget(self.source_table)
        v.addLayout(_bar(("چاپ گزارش جذب", "🖨️", "", self.print_report), ("خروجی Excel گزارش جذب", "📊", "", self.export_report)))
        return w

    def refresh_report(self) -> None:
        self.report_rows = rec.pipeline_report(company_id())
        fill(self.report_table, [self._report_row(r) for r in self.report_rows])
        fill(self.source_table, [list(r) for r in rec.source_report(company_id())])

    @staticmethod
    def _report_row(r) -> list:
        o = r["opening"]
        return [o.label, o.status_label, o.headcount] + [r["counts"][s] for s in rec.STAGES] + [
            P(r["days_to_hire"]) if r["days_to_hire"] is not None else "—"]

    def _report(self):
        headers = ["فرصت شغلی", "وضعیت", "نیرو"] + [rec.STAGES[s] for s in rec.STAGES] + ["میانگین روز تا استخدام"]
        return "گزارش جذب و استخدام", headers, [self._report_row(r) for r in self.report_rows]

    def print_report(self) -> bool:
        if not self.report_rows:
            return False
        report_export.print_report(self, *self._report())
        return True

    def export_report(self) -> bool:
        if not self.report_rows:
            return False
        report_export.export_report_excel(self, *self._report())
        return True
