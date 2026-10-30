"""R368: ارزیابی عملکرد — قالب معیارها، دوره‌ها، ارزیابی مدیر و نهایی‌کردن، خودارزیابی و نتایج."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from peecha.services import hr as hr_service
from peecha.services import hr_appraisals as ap
from peecha.services import hr_leave
from peecha.ui import report_export, theme
from peecha.ui.screens.fixed_assets import P, combo, company_id, fill, selected_data, set_combo, table, user_id
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


def _score(value) -> str:
    return P(f"{value:f}") if value is not None else "—"


def _score_spin(value: int | None) -> QSpinBox:
    box = QSpinBox()
    box.setRange(1, 5)
    box.setValue(value or 3)
    return box


class _ScoreTable(QWidget):
    """جدول معیارها با یک ستون امتیاز قابل ویرایش (۱ تا ۵)."""

    def __init__(self, editable_header: str) -> None:
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.table = table(["معیار", "وزن", "خودارزیابی", "ارزیابی مدیر", editable_header])
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        v.addWidget(self.table)
        self.spins: dict[int, QSpinBox] = {}

    def show_scores(self, scores, editable: bool, use_manager: bool) -> None:
        self.table.setRowCount(len(scores))
        self.spins = {}
        for r, s in enumerate(scores):
            for c, text in enumerate([s.title, P(f"{s.weight.normalize():f}٪"), _score(s.self_score), _score(s.manager_score)]):
                self.table.setItem(r, c, QTableWidgetItem(text))
            spin = _score_spin(s.manager_score if use_manager else s.self_score)
            spin.setEnabled(editable)
            self.table.setCellWidget(r, 4, spin)
            self.spins[s.criterion_id] = spin

    def values(self) -> dict[int, int]:
        return {cid: spin.value() for cid, spin in self.spins.items()}


class HrAppraisalsScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.templates: list = []
        self.cycles: list = []
        self.appraisals: list = []
        self.current = None
        self.mine = None
        self._template_id: int | None = None
        self._criteria: list[ap.CriterionFields] = []
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "ارزیابی عملکرد", "قالب معیارها با وزن، دورهٔ ارزیابی برای همهٔ کارکنان، خودارزیابی کارمند، ارزیابی مدیر واحد با امتیاز "
            "۱ تا ۵ و امتیاز وزنی، نهایی‌کردن توسط منابع انسانی و گزارش نتایج."))
        self.tabs = QTabWidget()
        self.review_tab = self._review_tab()
        self.self_tab = self._self_tab()
        self.tabs.addTab(self.review_tab, "ارزیابی کارکنان")
        self.tabs.addTab(self.self_tab, "خودارزیابی من")
        self.tabs.addTab(self._cycles_tab(), "دوره‌ها")
        self.tabs.addTab(self._templates_tab(), "قالب‌ها و معیارها")
        self.tabs.addTab(self._report_tab(), "نتایج")
        layout.addWidget(self.tabs, 1)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def _status(self, text: str, ok: bool) -> None:
        theme.set_status_label(self.status_label, text, ok=ok)

    # --- قالب‌ها ------------------------------------------------------------------------------------------------------
    def _templates_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.template_table = table(["کد", "نام", "تعداد معیار", "جمع وزن", "فعال", "در دوره به کار رفته"])
        self.template_table.itemSelectionChanged.connect(self._load_template)
        v.addWidget(self.template_table, 1)
        self.t_code, self.t_name = QLineEdit(), QLineEdit()
        self.t_active = QCheckBox("فعال")
        self.t_active.setChecked(True)
        v.addWidget(FieldGrid([FieldSpec("t_code", "کد قالب", self.t_code, span=1), FieldSpec("t_name", "نام قالب", self.t_name, span=1),
                               FieldSpec("t_active", "", self.t_active, span=1)]))
        crit = QHBoxLayout()
        self.cr_title, self.cr_desc = QLineEdit(), QLineEdit()
        self.cr_weight = QSpinBox()
        self.cr_weight.setRange(1, 100)
        self.cr_weight.setSuffix("٪")
        crit.addWidget(FieldGrid([FieldSpec("cr_title", "معیار", self.cr_title, span=1), FieldSpec("cr_weight", "وزن", self.cr_weight, span=1),
                                  FieldSpec("cr_desc", "توضیح", self.cr_desc, span=1)]), 1)
        for label, glyph, kind, slot in (("افزودن معیار", "➕", "", self.add_criterion),
                                         ("برداشتن معیار انتخاب‌شده", "➖", "danger", self.remove_criterion)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            crit.addWidget(button)
        v.addLayout(crit)
        self.criteria_table = table(["معیار", "وزن", "توضیح"])
        self.criteria_table.setMaximumHeight(170)
        v.addWidget(self.criteria_table)
        v.addLayout(_bar(("ذخیرهٔ قالب", "💾", "primary", self.save_template), ("قالب جدید", "🆕", "", self.new_template)))
        return w

    def _show_criteria(self) -> None:
        fill(self.criteria_table, [[c.title, P(f"{decimal.Decimal(c.weight).normalize():f}٪"), c.description or ""] for c in self._criteria],
             list(range(len(self._criteria))))

    def _load_template(self) -> None:
        t = next((x for x in self.templates if x.template_id == selected_data(self.template_table)), None)
        if t is None:
            return
        self._template_id = t.template_id
        self.t_code.setText(t.code)
        self.t_name.setText(t.name)
        self.t_active.setChecked(t.is_active)
        self._criteria = [ap.CriterionFields(c.title, c.weight, c.description) for c in t.criteria]
        self._show_criteria()

    def new_template(self) -> None:
        self._template_id = None
        self.template_table.clearSelection()
        self.t_code.clear()
        self.t_name.clear()
        self.t_active.setChecked(True)
        self._criteria = []
        self._show_criteria()

    def add_criterion(self) -> bool:
        if not self.cr_title.text().strip():
            self._status("عنوان معیار را وارد کنید.", False)
            return False
        self._criteria.append(ap.CriterionFields(self.cr_title.text().strip(), decimal.Decimal(self.cr_weight.value()), self.cr_desc.text()))
        self.cr_title.clear()
        self.cr_desc.clear()
        self._show_criteria()
        total = sum((decimal.Decimal(c.weight) for c in self._criteria), decimal.Decimal(0))
        self._status(f"جمع وزن معیارها: {P(total)}٪ (باید ۱۰۰ باشد).", total == 100)
        return True

    def remove_criterion(self) -> None:
        index = selected_data(self.criteria_table)
        if index is not None:
            del self._criteria[index]
            self._show_criteria()

    def save_template(self) -> int | None:
        try:
            template_id = ap.save_template(company_id(), self.t_code.text(), self.t_name.text(), self._criteria, self._template_id,
                                           self.t_active.isChecked())
        except ValueError as exc:
            self._status(str(exc), False)
            return None
        self.new_template()
        self.refresh()
        self._status("قالب ارزیابی ذخیره شد.", True)
        return template_id

    # --- دوره‌ها -------------------------------------------------------------------------------------------------------
    def _cycles_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.cycle_table = table(["عنوان", "قالب", "از", "تا", "خودارزیابی", "وضعیت", "ارزیابی‌ها", "نهایی‌شده"])
        v.addWidget(self.cycle_table, 1)
        self.cy_title = QLineEdit()
        self.cy_template = combo([], "—")
        self.cy_from, self.cy_to = JalaliDateEdit(), JalaliDateEdit()
        self.cy_self = QCheckBox("خودارزیابی کارمند")
        self.cy_self.setChecked(True)
        self.cy_unit = combo([], "— همهٔ واحدها —")
        v.addWidget(FieldGrid([FieldSpec("cy_title", "عنوان دوره", self.cy_title, span=1), FieldSpec("cy_template", "قالب", self.cy_template, span=1),
                               FieldSpec("cy_self", "", self.cy_self, span=1), FieldSpec("cy_from", "از تاریخ", self.cy_from, span=1),
                               FieldSpec("cy_to", "تا تاریخ", self.cy_to, span=1), FieldSpec("cy_unit", "واحد سازمانی (برای بازکردن)", self.cy_unit, span=1)]))
        v.addLayout(_bar(("ذخیرهٔ دورهٔ جدید", "💾", "primary", self.save_cycle),
                         ("بازکردن دوره و ساخت ارزیابی کارکنان", "▶️", "", self.open_cycle),
                         ("بستن دورهٔ انتخاب‌شده", "⏹️", "danger", self.close_cycle)))
        return w

    def save_cycle(self) -> int | None:
        if self.cy_template.currentData() is None:
            self._status("قالب ارزیابی را انتخاب کنید.", False)
            return None
        try:
            cycle_id = ap.save_cycle(company_id(), self.cy_title.text(), self.cy_template.currentData(), self.cy_from.date(),
                                     self.cy_to.date(), self.cy_self.isChecked())
        except ValueError as exc:
            self._status(str(exc), False)
            return None
        self.cy_title.clear()
        self.refresh()
        self._status("دورهٔ ارزیابی ذخیره شد؛ برای ساخت ارزیابی‌ها آن را باز کنید.", True)
        return cycle_id

    def _cycle_id(self):
        cid = selected_data(self.cycle_table)
        if cid is None:
            self._status("یک دوره را از جدول انتخاب کنید.", False)
        return cid

    def open_cycle(self) -> int | None:
        cid = self._cycle_id()
        if cid is None:
            return None
        try:
            n = ap.open_cycle(company_id(), cid, self.cy_unit.currentData())
        except ValueError as exc:
            self._status(str(exc), False)
            return None
        self.refresh()
        self._status(f"دوره باز شد و {P(n)} ارزیابی ساخته شد.", True)
        return n

    def close_cycle(self) -> bool:
        cid = self._cycle_id()
        if cid is None:
            return False
        try:
            left = ap.close_cycle(company_id(), cid)
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self.refresh()
        self._status("دوره بسته شد." + (f" {P(left)} ارزیابی نهایی نشده بود." if left else ""), True)
        return True

    # --- ارزیابی کارکنان ----------------------------------------------------------------------------------------------
    def _review_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel("دوره:"))
        self.review_cycle = QComboBox()
        self.review_cycle.currentIndexChanged.connect(self.refresh_appraisals)
        row.addWidget(self.review_cycle, 1)
        self.only_mine = QCheckBox("فقط ارزیابی‌هایی که من ارزیابشان هستم")
        self.only_mine.toggled.connect(self.refresh_appraisals)
        row.addWidget(self.only_mine)
        v.addLayout(row)
        self.appraisal_table = table(["کد", "کارمند", "واحد", "ارزیاب", "وضعیت", "امتیاز", "رده"])
        self.appraisal_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.appraisal_table.itemSelectionChanged.connect(self._load_appraisal)
        v.addWidget(self.appraisal_table, 1)
        self.review_label = QLabel("")
        self.review_label.setWordWrap(True)
        v.addWidget(self.review_label)
        self.review_scores = _ScoreTable("امتیاز مدیر (۱ تا ۵)")
        v.addWidget(self.review_scores, 1)
        self.rv_comment, self.rv_strengths, self.rv_improve, self.rv_goals = (QLineEdit() for _ in range(4))
        self.rv_reviewer = combo([], "—")
        v.addWidget(FieldGrid([FieldSpec("rv_strengths", "نقاط قوت", self.rv_strengths, span=1),
                               FieldSpec("rv_improve", "زمینه‌های بهبود", self.rv_improve, span=1),
                               FieldSpec("rv_goals", "اهداف دورهٔ بعد", self.rv_goals, span=1),
                               FieldSpec("rv_comment", "نظر مدیر", self.rv_comment, span=2),
                               FieldSpec("rv_reviewer", "تغییر ارزیاب", self.rv_reviewer, span=1)]))
        v.addLayout(_bar(("ثبت ارزیابی مدیر", "💾", "primary", self.submit_review),
                         ("نهایی‌کردن ارزیابی‌های انتخاب‌شده", "✅", "", self.finalize),
                         ("تغییر ارزیاب ارزیابی انتخاب‌شده", "👤", "", self.reassign),
                         ("چاپ فرم ارزیابی", "🖨️", "", self.print_appraisal)))
        return w

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        self.templates = ap.list_templates(cid)
        fill(self.template_table, [[t.code, t.name, len(t.criteria), P(f"{t.total_weight.normalize():f}٪"), "بله" if t.is_active else "خیر",
                                    "بله" if t.in_use else "خیر"] for t in self.templates], [t.template_id for t in self.templates])
        current = self.cy_template.currentData()
        self.cy_template.clear()
        self.cy_template.addItem("—", None)
        for t in self.templates:
            if t.is_active:
                self.cy_template.addItem(P(f"{t.code} — {t.name}"), t.template_id)
        set_combo(self.cy_template, current)
        units = [(f"{u.code} — {u.name}", u.org_unit_id) for u in hr_service.list_org_units(cid)]
        employees = [(f"{e.employee_code} — {e.full_name}", e.employee_id) for e in hr_service.list_employees(cid) if e.status == "ACTIVE"]
        for box, items, none in ((self.cy_unit, units, "— همهٔ واحدها —"), (self.rv_reviewer, employees, "—")):
            current = box.currentData()
            box.clear()
            box.addItem(none, None)
            for label, data in items:
                box.addItem(P(label), data)
            set_combo(box, current)
        self.cycles = ap.list_cycles(cid)
        fill(self.cycle_table, [[c.title, c.template_name, c.period_from, c.period_to, "بله" if c.self_assessment else "خیر",
                                 c.status_label, c.total, c.finalized] for c in self.cycles], [c.cycle_id for c in self.cycles])
        for box in (self.review_cycle, self.report_cycle):
            current = box.currentData()
            box.blockSignals(True)
            box.clear()
            for c in self.cycles:
                if c.status_code != "DRAFT":
                    box.addItem(P(f"{c.title} ({c.status_label})"), c.cycle_id)
            index = box.findData(current)
            box.setCurrentIndex(index if index >= 0 else 0)
            box.blockSignals(False)
        self.refresh_appraisals()
        self.refresh_mine()
        self.refresh_report()

    def refresh_appraisals(self) -> None:
        cid = company_id()
        self.appraisal_table.setRowCount(0)
        self.review_scores.show_scores([], False, True)
        self.current = None
        if cid is None or self.review_cycle.currentData() is None:
            return
        me = hr_leave.employee_of_user(cid, user_id()) if user_id() else None
        self.appraisals = ap.list_appraisals(cid, self.review_cycle.currentData(),
                                             reviewer_employee_id=me if self.only_mine.isChecked() and me else None)
        fill(self.appraisal_table, [[a.employee_code, a.employee_name, a.org_unit or "—", a.reviewer_name or "—", a.status_label,
                                     _score(a.overall_score), a.band_label] for a in self.appraisals],
             [a.appraisal_id for a in self.appraisals])

    def _selected_ids(self) -> list[int]:
        rows = sorted({i.row() for i in self.appraisal_table.selectedIndexes()})
        return [self.appraisal_table.item(r, 0).data(Qt.UserRole) for r in rows]

    def _load_appraisal(self) -> None:
        ids = self._selected_ids()
        if len(ids) != 1:
            return
        a = self.current = ap.get_appraisal(company_id(), ids[0])
        self.review_label.setText(f"{a.employee_name} ({a.org_unit or '—'}) — {a.status_label}"
                                  + (f" | نظر کارمند: {a.self_comment}" if a.self_comment else ""))
        editable = a.status_code in ("PENDING_MANAGER", "REVIEWED") and ap.can_review(company_id(), user_id(), a)
        self.review_scores.show_scores(a.scores, editable, True)
        self.rv_comment.setText(a.manager_comment)
        self.rv_strengths.setText(a.strengths)
        self.rv_improve.setText(a.improvements)
        self.rv_goals.setText(a.goals)
        set_combo(self.rv_reviewer, a.reviewer_employee_id)

    def open_appraisal(self, appraisal_id: int) -> None:
        """از کارتابل: همان ارزیابی در دوره‌اش انتخاب می‌شود."""
        self.refresh()
        row = next((a for a in ap.list_appraisals(company_id()) if a.appraisal_id == appraisal_id), None)
        if row is None:
            return
        self.review_cycle.setCurrentIndex(self.review_cycle.findData(row.cycle_id))
        self.refresh_appraisals()
        index = next((i for i, a in enumerate(self.appraisals) if a.appraisal_id == appraisal_id), None)
        if index is not None:
            self.appraisal_table.setCurrentCell(index, 0)
            self._load_appraisal()
        self.tabs.setCurrentWidget(self.review_tab)

    def _reselect(self, appraisal_id: int) -> None:
        self.refresh()
        index = next((i for i, a in enumerate(self.appraisals) if a.appraisal_id == appraisal_id), None)
        if index is not None:
            self.appraisal_table.setCurrentCell(index, 0)
            self._load_appraisal()

    def submit_review(self) -> bool:
        if self.current is None:
            self._status("یک ارزیابی را انتخاب کنید.", False)
            return False
        try:
            score = ap.submit_review(company_id(), user_id(), self.current.appraisal_id, self.review_scores.values(),
                                     comment=self.rv_comment.text(), strengths=self.rv_strengths.text(),
                                     improvements=self.rv_improve.text(), goals=self.rv_goals.text())
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self._reselect(self.current.appraisal_id)
        self._status(f"ارزیابی ثبت شد؛ امتیاز وزنی {_score(score)} ({ap.BAND_LABELS[ap.band(score)]}).", True)
        return True

    def finalize(self) -> int:
        ids = self._selected_ids()
        if not ids:
            self._status("ارزیابی‌هایی را برای نهایی‌کردن انتخاب کنید.", False)
            return 0
        try:
            n = ap.finalize(company_id(), user_id(), ids)
        except ValueError as exc:
            self._status(str(exc), False)
            return 0
        self.refresh()
        self._status(f"{P(n)} ارزیابی نهایی شد.", True)
        return n

    def reassign(self) -> bool:
        if self.current is None:
            self._status("یک ارزیابی را انتخاب کنید.", False)
            return False
        try:
            ap.reassign_reviewer(company_id(), self.current.appraisal_id, self.rv_reviewer.currentData())
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self._reselect(self.current.appraisal_id)
        self._status("ارزیاب تغییر کرد.", True)
        return True

    def print_appraisal(self) -> bool:
        a = self.current
        if a is None:
            self._status("یک ارزیابی را انتخاب کنید.", False)
            return False
        rows = [[s.title, P(f"{s.weight.normalize():f}٪"), _score(s.self_score), _score(s.manager_score)] for s in a.scores]
        head = [("کارمند", f"{a.employee_code} — {a.employee_name}"), ("واحد", a.org_unit or "—"), ("ارزیاب", a.reviewer_name or "—"),
                ("دوره", a.cycle_title), ("امتیاز وزنی", _score(a.overall_score)), ("رده", a.band_label),
                ("نقاط قوت", a.strengths or "—"), ("زمینه‌های بهبود", a.improvements or "—"), ("اهداف دورهٔ بعد", a.goals or "—")]
        report_export.print_report(self, "فرم ارزیابی عملکرد", ["معیار", "وزن", "خودارزیابی", "امتیاز مدیر"], rows, filters=head)
        return True

    # --- خودارزیابی ---------------------------------------------------------------------------------------------------
    def _self_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.self_label = QLabel("")
        self.self_label.setWordWrap(True)
        v.addWidget(self.self_label)
        self.self_scores = _ScoreTable("امتیاز من (۱ تا ۵)")
        v.addWidget(self.self_scores, 1)
        self.self_comment = QLineEdit()
        v.addWidget(FieldGrid([FieldSpec("self_comment", "توضیح من", self.self_comment, span=3)]))
        v.addLayout(_bar(("ثبت خودارزیابی", "📤", "primary", self.submit_self)))
        self.self_history = table(["دوره", "امتیاز", "رده"])
        self.self_history.setMaximumHeight(150)
        v.addWidget(QLabel("ارزیابی‌های نهایی من"))
        v.addWidget(self.self_history)
        return w

    def refresh_mine(self) -> None:
        cid = company_id()
        me = hr_leave.employee_of_user(cid, user_id()) if cid and user_id() else None
        self.mine = None
        if me is None:
            self.self_label.setText("پروندهٔ پرسنلی به کاربر شما وصل نیست.")
            self.self_scores.show_scores([], False, False)
            self.self_history.setRowCount(0)
            return
        pending = [a for a in ap.list_appraisals(cid, employee_id=me) if a.status_code == "PENDING_SELF"]
        if pending:
            self.mine = ap.get_appraisal(cid, pending[0].appraisal_id)
            self.self_label.setText(f"خودارزیابی دورهٔ «{self.mine.cycle_title}»: به هر معیار از ۱ تا ۵ امتیاز بدهید.")
            self.self_scores.show_scores(self.mine.scores, True, False)
        else:
            self.self_label.setText("خودارزیابی بازی ندارید.")
            self.self_scores.show_scores([], False, False)
        fill(self.self_history, [[t, _score(s), b] for t, s, b in ap.history(cid, me)])

    def submit_self(self) -> bool:
        if self.mine is None:
            self._status("خودارزیابی بازی ندارید.", False)
            return False
        try:
            ap.submit_self(company_id(), user_id(), self.mine.appraisal_id, self.self_scores.values(), self.self_comment.text())
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self.self_comment.clear()
        self.refresh()
        self._status("خودارزیابی ثبت و برای مدیر فرستاده شد.", True)
        return True

    def open_self(self) -> None:
        self.refresh()
        self.tabs.setCurrentWidget(self.self_tab)

    # --- نتایج --------------------------------------------------------------------------------------------------------
    def _report_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel("دوره:"))
        self.report_cycle = QComboBox()
        self.report_cycle.currentIndexChanged.connect(self.refresh_report)
        row.addWidget(self.report_cycle, 1)
        v.addLayout(row)
        self.report_label = QLabel("")
        v.addWidget(self.report_label)
        self.band_table = table(["رده", "تعداد"])
        self.band_table.setMaximumHeight(200)
        v.addWidget(self.band_table)
        self.unit_table = table(["واحد", "تعداد", "میانگین امتیاز"])
        v.addWidget(self.unit_table, 1)
        v.addLayout(_bar(("خروجی Excel نتایج کارکنان", "📊", "", self.export_results)))
        return w

    def refresh_report(self) -> None:
        cycle = self.report_cycle.currentData()
        self.band_table.setRowCount(0)
        self.unit_table.setRowCount(0)
        if cycle is None or company_id() is None:
            self.report_label.setText("")
            return
        r = ap.cycle_report(company_id(), cycle)
        self.report_label.setText(f"میانگین امتیاز دوره: {_score(r['average'])}")
        fill(self.band_table, [list(b) for b in r["bands"]])
        fill(self.unit_table, [[u, n, _score(avg)] for u, n, avg in r["units"]])

    def export_results(self) -> bool:
        cycle = self.report_cycle.currentData()
        if cycle is None:
            return False
        rows = [[a.employee_code, a.employee_name, a.org_unit, a.reviewer_name, a.status_label, _score(a.overall_score), a.band_label]
                for a in ap.list_appraisals(company_id(), cycle)]
        report_export.export_report_excel(self, "نتایج ارزیابی عملکرد", ["کد", "کارمند", "واحد", "ارزیاب", "وضعیت", "امتیاز", "رده"], rows)
        return True
