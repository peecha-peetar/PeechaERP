"""R366: زبانهٔ «درخواست تغییر» فرم پروژه‌ها."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget

from peecha.services.projects import changes as ch
from peecha.ui.screens.fixed_assets import P, company_id, dec, fill, money, selected_data, table, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec


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


def _q(value: decimal.Decimal) -> str:
    return P(f"{value.normalize():f}")


class ProjectChangesTab(QWidget):
    def __init__(self, status) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self._status = status
        self.project_id: int | None = None
        self.changes: list = []
        self.lines: list[ch.LineFields] = []
        self._change_id: int | None = None
        self.ask_reason = None  # برای آزمون: تابعی که دلیل رد را برمی‌گرداند
        self.on_decided = None  # فرم پروژه پس از تایید یا رد، مبلغ و تاریخ پروژه را دوباره می‌خواند
        v = QVBoxLayout(self)
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        v.addWidget(self.summary_label)
        self.change_table = table(["شماره", "عنوان", "تغییر مبلغ", "تغییر مدت (روز)", "ردیف‌های جدید", "وضعیت", "توضیح تصمیم"])
        self.change_table.itemSelectionChanged.connect(self._load_change)
        v.addWidget(self.change_table, 1)
        self.title_field, self.reason_field, self.amount_field = QLineEdit(), QLineEdit(), QLineEdit()
        self.amount_field.setPlaceholderText("۰ (کاهش با علامت منفی)")
        self.days_field = QSpinBox()
        self.days_field.setRange(-3650, 3650)
        v.addWidget(FieldGrid([
            FieldSpec("chg_title", "عنوان", self.title_field, span=1), FieldSpec("chg_amount", "تغییر مبلغ قرارداد", self.amount_field, span=1),
            FieldSpec("chg_days", "تغییر مدت (روز)", self.days_field, span=1), FieldSpec("chg_reason", "علت", self.reason_field, span=3)]))
        self.line_code, self.line_desc, self.line_unit, self.line_qty, self.line_price = (QLineEdit() for _ in range(5))
        row = QHBoxLayout()
        row.addWidget(FieldGrid([
            FieldSpec("chg_lcode", "کد ردیف جدید", self.line_code, span=1), FieldSpec("chg_ldesc", "شرح", self.line_desc, span=2),
            FieldSpec("chg_lunit", "واحد", self.line_unit, span=1), FieldSpec("chg_lqty", "مقدار", self.line_qty, span=1),
            FieldSpec("chg_lprice", "بهای واحد", self.line_price, span=1)]), 1)
        for label, glyph, kind, slot in (("افزودن ردیف جدید فهرست بها به درخواست", "➕", "", self.add_line),
                                         ("برداشتن ردیف انتخاب‌شده", "➖", "danger", self.remove_line)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            row.addWidget(button)
        v.addLayout(row)
        self.line_table = table(["کد", "شرح", "واحد", "مقدار", "بهای واحد", "مبلغ"])
        self.line_table.setMaximumHeight(130)
        v.addWidget(self.line_table)
        v.addLayout(_bar(("ذخیره و ارسال برای تایید", "📤", "primary", lambda: self.save(True)),
                         ("ذخیرهٔ پیش‌نویس", "💾", "", lambda: self.save(False)), ("درخواست جدید", "🆕", "", self.new_change),
                         ("حذف درخواست", "🗑️", "danger", self.delete_change),
                         ("تایید درخواست انتخاب‌شده", "✅", "", self.approve), ("رد درخواست انتخاب‌شده", "❌", "danger", self.reject)))

    def set_project(self, project) -> None:
        self.project_id = project.project_id if project else None
        self.new_change()
        self.refresh()

    def refresh(self) -> None:
        self.change_table.setRowCount(0)
        if company_id() is None or self.project_id is None:
            self.summary_label.setText("")
            return
        self.changes = ch.list_changes(company_id(), self.project_id)
        fill(self.change_table, [[c.change_no, c.title, c.amount_change, c.days_change, len(c.lines), c.status_label, c.decision_note]
                                 for c in self.changes], [c.change_id for c in self.changes])
        amount, days, open_count = ch.approved_totals(company_id(), self.project_id)
        self.summary_label.setText(f"تغییرات تاییدشده: مبلغ {money(amount)} و مدت {P(days)} روز | درخواست‌های باز: {P(open_count)}")

    def _show_lines(self) -> None:
        fill(self.line_table, [[ln.code, ln.description, ln.unit, _q(ln.quantity), ln.unit_price,
                                (ln.quantity * ln.unit_price).quantize(decimal.Decimal("0.01"))] for ln in self.lines],
             list(range(len(self.lines))))

    def _load_change(self) -> None:
        cid = selected_data(self.change_table)
        c = next((x for x in self.changes if x.change_id == cid), None)
        if c is None:
            return
        self._change_id = c.change_id
        self.title_field.setText(c.title)
        self.reason_field.setText(c.reason)
        self.amount_field.setText(_q(c.amount_change) if c.amount_change else "")
        self.days_field.setValue(c.days_change)
        self.lines = list(c.lines)
        self._show_lines()

    def new_change(self) -> None:
        self._change_id = None
        self.change_table.clearSelection()
        for f in (self.title_field, self.reason_field, self.amount_field):
            f.clear()
        self.days_field.setValue(0)
        self.lines = []
        self._show_lines()

    def add_line(self) -> bool:
        try:
            line = ch.LineFields(self.line_code.text().strip(), self.line_desc.text().strip(), self.line_unit.text().strip(),
                                 dec(self.line_qty.text()), dec(self.line_price.text()))
            ch.clean_lines(self.lines + [line])
        except (ValueError, decimal.InvalidOperation) as exc:
            self._status(str(exc) if isinstance(exc, ValueError) else "مقدار یا بها نامعتبر است.", False)
            return False
        self.lines.append(line)
        for f in (self.line_code, self.line_desc, self.line_unit, self.line_qty, self.line_price):
            f.clear()
        self._show_lines()
        return True

    def remove_line(self) -> None:
        index = selected_data(self.line_table)
        if index is not None:
            del self.lines[index]
            self._show_lines()

    def save(self, submit: bool) -> int | None:
        if self.project_id is None:
            self._status("یک پروژه را انتخاب کنید.", False)
            return None
        try:
            change_id = ch.save_change(company_id(), user_id(), self.project_id, ch.ChangeFields(
                self.title_field.text(), self.reason_field.text(), dec(self.amount_field.text()), self.days_field.value(), self.lines),
                self._change_id, submit=submit)
        except (ValueError, decimal.InvalidOperation) as exc:
            self._status(str(exc) if isinstance(exc, ValueError) else "مبلغ نامعتبر است.", False)
            return None
        self.new_change()
        self.refresh()
        self._status("درخواست تغییر برای تایید فرستاده شد." if submit else "درخواست تغییر ذخیره شد.", True)
        return change_id

    def _selected(self):
        cid = selected_data(self.change_table)
        if cid is None:
            self._status("یک درخواست تغییر را انتخاب کنید.", False)
        return cid

    def delete_change(self) -> bool:
        cid = self._selected()
        if cid is None:
            return False
        try:
            ch.delete_change(company_id(), cid)
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self.new_change()
        self.refresh()
        self._status("درخواست تغییر حذف شد.", True)
        return True

    def _after_decision(self, text: str) -> None:
        self.new_change()
        self.refresh()
        self._status(text, True)
        if self.on_decided:
            self.on_decided()

    def approve(self) -> bool:
        cid = self._selected()
        if cid is None:
            return False
        try:
            ch.approve(company_id(), user_id(), cid)
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self._after_decision("درخواست تغییر تایید شد؛ مبلغ قرارداد، پایان هدف و فهرست بها به‌روز شد.")
        return True

    def reject(self) -> bool:
        cid = self._selected()
        if cid is None:
            return False
        if self.ask_reason is not None:
            reason, ok = self.ask_reason(), True
        else:
            reason, ok = QInputDialog.getText(self, "رد درخواست تغییر", "دلیل رد:")
        if not ok:
            return False
        try:
            ch.reject(company_id(), user_id(), cid, reason)
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self._after_decision("درخواست تغییر رد شد.")
        return True
