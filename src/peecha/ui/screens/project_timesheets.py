"""R364: ثبت کارکرد پروژه، تایید و رد کارکرد ارسال‌شده و نرخ ساعتی کارکنان."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton, QTabWidget, QVBoxLayout,
    QWidget,
)

from peecha.services import hr as hr_service
from peecha.services import hr_leave
from peecha.services.projects import core as prj
from peecha.services.projects import schedule as sch
from peecha.services.projects import timesheets as ts
from peecha.ui import theme
from peecha.ui.screens.fixed_assets import P, combo, company_id, dec, fill, selected_data, set_combo, table, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec, JalaliDateEdit, build_page_header

_ENTRY_HEADERS = ["تاریخ", "کارمند", "پروژه", "فعالیت", "ساعت", "شرح", "وضعیت", "توضیح تاییدکننده"]


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


def _h(value: decimal.Decimal) -> str:
    return P(f"{value.normalize():f}")


def _selected_ids(t) -> list[int]:
    rows = sorted({i.row() for i in t.selectedIndexes()})
    return [t.item(r, 0).data(Qt.UserRole) for r in rows]


class ProjectTimesheetsScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.entries: list = []
        self.pending: list = []
        self.rates: list = []
        self._entry_id: int | None = None
        self.ask_reason = None  # برای آزمون: تابعی که دلیل رد را برمی‌گرداند
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "ثبت و تایید کارکرد پروژه", "ساعت‌های کار روی هر پروژه و فعالیت را ثبت و برای تایید بفرستید. مدیر پروژه یا دارندهٔ مجوز "
            "تایید، کارکرد را تایید یا رد می‌کند؛ هزینهٔ کارکرد با نرخ ساعتی روز کار حساب می‌شود و سند حسابداری نمی‌سازد."))
        self.tabs = QTabWidget()
        self.tabs.addTab(self._entry_tab(), "ثبت کارکرد")
        self.approve_tab = self._approve_tab()
        self.tabs.addTab(self.approve_tab, "تایید کارکرد")
        self.tabs.addTab(self._rates_tab(), "نرخ ساعتی")
        layout.addWidget(self.tabs, 1)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def _status(self, text: str, ok: bool) -> None:
        theme.set_status_label(self.status_label, text, ok=ok)

    # --- ثبت ---------------------------------------------------------------------------------------------------------
    def _entry_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.project_combo = combo([], "—")
        self.project_combo.currentIndexChanged.connect(self._fill_tasks)
        self.task_combo = combo([], "— بدون فعالیت —")
        self.employee_combo = combo([], "—")
        self.date_field = JalaliDateEdit()
        self.hours_field = QDoubleSpinBox()
        self.hours_field.setRange(0, 24)
        self.hours_field.setSingleStep(0.5)
        self.description_field = QLineEdit()
        v.addWidget(FieldGrid([
            FieldSpec("ts_project", "پروژه", self.project_combo, span=1), FieldSpec("ts_task", "فعالیت", self.task_combo, span=1),
            FieldSpec("ts_employee", "کارمند", self.employee_combo, span=1), FieldSpec("ts_date", "روز کارکرد", self.date_field, span=1),
            FieldSpec("ts_hours", "ساعت", self.hours_field, span=1), FieldSpec("ts_desc", "شرح کار", self.description_field, span=1),
        ]))
        v.addLayout(_bar(("ذخیره و ارسال برای تایید", "📤", "primary", lambda: self.save_entry(True)),
                         ("ذخیرهٔ پیش‌نویس", "💾", "", lambda: self.save_entry(False)),
                         ("کارکرد جدید", "🆕", "", self.new_entry),
                         ("ارسال ردیف‌های انتخاب‌شده برای تایید", "📨", "", self.submit_selected),
                         ("حذف کارکرد", "🗑️", "danger", self.delete_entry), ("به‌روزرسانی", "🔄", "", self.refresh)))
        filters = QHBoxLayout()
        filters.addWidget(QLabel("نمایش:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("همهٔ وضعیت‌ها", None)
        for code, label in ts.STATUSES.items():
            self.filter_combo.addItem(label, code)
        self.filter_combo.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.filter_combo)
        self.total_label = QLabel("")
        filters.addWidget(self.total_label, 1)
        v.addLayout(filters)
        self.entry_table = table(_ENTRY_HEADERS)
        self.entry_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.entry_table.itemSelectionChanged.connect(self._load_entry)
        v.addWidget(self.entry_table, 1)
        return w

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        projects = [(p.label, p.project_id) for p in prj.list_projects(cid, ts.OPEN_PROJECT_STATUSES)]
        employees = [(f"{e.employee_code} — {e.full_name}", e.employee_id) for e in hr_service.list_employees(cid) if e.status == "ACTIVE"]
        for box, items, none in ((self.project_combo, projects, "—"), (self.employee_combo, employees, "—"),
                                 (self.rate_employee_combo, employees, "همهٔ کارکنان (نرخ پیش‌فرض)")):
            current = box.currentData()
            box.blockSignals(True)
            box.clear()
            box.addItem(none, None)
            for label, data in items:
                box.addItem(P(label), data)
            set_combo(box, current)
            box.blockSignals(False)
        if self.employee_combo.currentData() is None and user_id() is not None:
            set_combo(self.employee_combo, hr_leave.employee_of_user(cid, user_id()))
        self._fill_tasks()
        self.entries = ts.list_entries(cid, status=self.filter_combo.currentData())
        fill(self.entry_table, [[e.work_date, e.employee_name, e.project_label, e.task_name or "—", _h(e.hours), e.description,
                                 e.status_label, e.decision_note] for e in self.entries], [e.entry_id for e in self.entries])
        self.total_label.setText(f"جمع ساعت: {_h(sum((e.hours for e in self.entries), decimal.Decimal(0)))}")
        self.pending = ts.pending_for(cid, user_id()) if user_id() is not None else []
        fill(self.pending_table, [[e.work_date, e.employee_name, e.project_label, e.task_name or "—", _h(e.hours), e.description,
                                   e.status_label, ""] for e in self.pending], [e.entry_id for e in self.pending])
        self.rates = ts.list_rates(cid)
        fill(self.rate_table, [[r.employee_name, r.valid_from, r.hourly_cost] for r in self.rates], [r.rate_id for r in self.rates])

    def _fill_tasks(self) -> None:
        pid = self.project_combo.currentData()
        current = self.task_combo.currentData()
        self.task_combo.clear()
        self.task_combo.addItem("— بدون فعالیت —", None)
        if pid is not None:
            for t in sch.compute(company_id(), pid).tasks:
                if not t.is_summary:
                    self.task_combo.addItem(P(f"{t.wbs} {t.name}"), t.task_id)
        set_combo(self.task_combo, current)

    def _load_entry(self) -> None:
        ids = _selected_ids(self.entry_table)
        e = next((x for x in self.entries if ids and x.entry_id == ids[0]), None)
        if e is None or len(ids) != 1:
            return
        self._entry_id = e.entry_id
        set_combo(self.project_combo, e.project_id)
        self._fill_tasks()
        set_combo(self.task_combo, e.task_id)
        set_combo(self.employee_combo, e.employee_id)
        self.date_field.setDate(e.work_date)
        self.hours_field.setValue(float(e.hours))
        self.description_field.setText(e.description)

    def new_entry(self) -> None:
        self._entry_id = None
        self.entry_table.clearSelection()
        self.hours_field.setValue(0)
        self.description_field.clear()
        self.date_field.setDate(datetime.date.today())

    def save_entry(self, submit: bool) -> int | None:
        pid, emp = self.project_combo.currentData(), self.employee_combo.currentData()
        if pid is None or emp is None:
            self._status("پروژه و کارمند را انتخاب کنید.", False)
            return None
        try:
            entry_id = ts.save_entry(company_id(), user_id(), ts.EntryFields(
                pid, emp, self.date_field.date(), decimal.Decimal(str(self.hours_field.value())), self.task_combo.currentData(),
                self.description_field.text()), self._entry_id, submit=submit)
        except ValueError as exc:
            self._status(str(exc), False)
            return None
        self.new_entry()
        self.refresh()
        self._status("کارکرد ثبت و برای تایید فرستاده شد." if submit else "کارکرد به‌صورت پیش‌نویس ذخیره شد.", True)
        return entry_id

    def submit_selected(self) -> int:
        ids = _selected_ids(self.entry_table)
        if not ids:
            self._status("ردیف‌های پیش‌نویس را از جدول انتخاب کنید.", False)
            return 0
        try:
            n = ts.submit(company_id(), ids)
        except ValueError as exc:
            self._status(str(exc), False)
            return 0
        self.refresh()
        self._status(f"{P(n)} ردیف برای تایید فرستاده شد.", True)
        return n

    def delete_entry(self) -> bool:
        ids = _selected_ids(self.entry_table)
        if len(ids) != 1:
            self._status("یک ردیف کارکرد را انتخاب کنید.", False)
            return False
        try:
            ts.delete_entry(company_id(), ids[0])
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self.new_entry()
        self.refresh()
        self._status("کارکرد حذف شد.", True)
        return True

    # --- تایید -------------------------------------------------------------------------------------------------------
    def _approve_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        hint = QLabel("کارکردهای ارسال‌شدهٔ پروژه‌هایی که مدیرشان هستید یا مجوز تاییدشان را دارید. چند ردیف را با هم انتخاب کنید.")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self.pending_table = table(_ENTRY_HEADERS)
        self.pending_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        v.addWidget(self.pending_table, 1)
        v.addLayout(_bar(("تایید ردیف‌های انتخاب‌شده", "✅", "primary", self.approve_selected),
                         ("رد ردیف‌های انتخاب‌شده", "❌", "danger", self.reject_selected), ("به‌روزرسانی", "🔄", "", self.refresh)))
        return w

    def approve_selected(self) -> int:
        ids = _selected_ids(self.pending_table)
        if not ids:
            self._status("ردیف‌هایی را برای تایید انتخاب کنید.", False)
            return 0
        try:
            n = ts.approve(company_id(), user_id(), ids)
        except ValueError as exc:
            self._status(str(exc), False)
            return 0
        self.refresh()
        self._status(f"{P(n)} ردیف کارکرد تایید شد.", True)
        return n

    def reject_selected(self) -> int:
        ids = _selected_ids(self.pending_table)
        if not ids:
            self._status("ردیف‌هایی را برای رد انتخاب کنید.", False)
            return 0
        if self.ask_reason is not None:
            reason, ok = self.ask_reason(), True
        else:
            reason, ok = QInputDialog.getText(self, "رد کارکرد", "دلیل رد کارکرد:")
        if not ok:
            return 0
        try:
            n = ts.reject(company_id(), user_id(), ids, reason)
        except ValueError as exc:
            self._status(str(exc), False)
            return 0
        self.refresh()
        self._status(f"{P(n)} ردیف کارکرد رد شد.", True)
        return n

    def show_approvals(self) -> None:
        self.tabs.setCurrentWidget(self.approve_tab)

    # --- نرخ ساعتی ---------------------------------------------------------------------------------------------------
    def _rates_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.rate_employee_combo = combo([], "همهٔ کارکنان (نرخ پیش‌فرض)")
        self.rate_date_field = JalaliDateEdit()
        self.rate_field = QLineEdit()
        self.rate_field.setPlaceholderText("۰")
        v.addWidget(FieldGrid([
            FieldSpec("rate_employee", "کارمند", self.rate_employee_combo, span=1),
            FieldSpec("rate_from", "معتبر از", self.rate_date_field, span=1),
            FieldSpec("rate_value", "هزینهٔ هر ساعت", self.rate_field, span=1)]))
        v.addLayout(_bar(("ذخیرهٔ نرخ", "💾", "primary", self.save_rate), ("حذف نرخ", "🗑️", "danger", self.delete_rate)))
        self.rate_table = table(["کارمند", "معتبر از", "هزینهٔ هر ساعت"])
        v.addWidget(self.rate_table, 1)
        return w

    def save_rate(self) -> int | None:
        try:
            rate_id = ts.save_rate(company_id(), self.rate_employee_combo.currentData(), self.rate_date_field.date(),
                                   dec(self.rate_field.text()))
        except (ValueError, decimal.InvalidOperation) as exc:
            self._status(str(exc) if isinstance(exc, ValueError) else "نرخ نامعتبر است.", False)
            return None
        self.rate_field.clear()
        self.refresh()
        self._status("نرخ ساعتی ذخیره شد.", True)
        return rate_id

    def delete_rate(self) -> bool:
        rate_id = selected_data(self.rate_table)
        if rate_id is None:
            self._status("یک نرخ را از جدول انتخاب کنید.", False)
            return False
        ts.delete_rate(company_id(), rate_id)
        self.refresh()
        self._status("نرخ حذف شد.", True)
        return True
