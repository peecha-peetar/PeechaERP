"""R323: فرم کامل انجام یک مرحلهٔ گردش کار (تایید یا کار).

هر مرحله فرم مشخص خودش را دارد: چه باید کرد، اطلاعات سند، سابقهٔ مراحل قبل و یادداشت‌ها، خانه‌های فرم همان مرحله
با کنترل همان لحظهٔ ورود، یادداشت و فقط دکمه‌های تصمیم مجاز. ثبت تصمیم همان tasks.decide است (منطق جدایی ندارد).
"""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter,
    QTextEdit, QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services.workflow import conditions, runtime, tasks
from peecha.services.workflow.common import WorkflowError
from peecha.ui.persian_numbers import NumberEdit
from peecha.ui.screens import module_style as ms
from peecha.ui.screens.fixed_assets import P, company_id, date_field, fill, table, user_id
from peecha.ui.widgets import JalaliDateEdit, mark_invalid

ms.ICONS.update({"برگشت برای اصلاح": ("↩️", ""), "ثبت یادداشت": ("💬", ""), "بازکردن سند": ("📂", ""),
                 "بستن فرم": ("✖️", ""), "ارجاع به فرد مناسب": ("↗️", "primary")})
_DECISION_BUTTONS = {"APPROVE": "تایید", "DONE": "انجام شد", "REJECT": "رد", "CHANGES": "برگشت برای اصلاح"}


def field_widget(f: dict) -> QWidget:
    kind = f.get("kind") or "text"
    if kind in ("number", "money"):
        w = NumberEdit()
        w.setProperty("numeric", True)
        return w
    if kind == "date":
        return date_field()
    if kind == "bool":
        return QCheckBox(f.get("label") or "")
    if kind == "choice":
        box = QComboBox()
        box.addItem("—", None)
        for c in f.get("choices") or []:
            box.addItem(str(c), c)
        return box
    if kind == "longtext":
        w = QTextEdit()
        w.setMaximumHeight(70)
        return w
    return QLineEdit()


def widget_value(w: QWidget):
    if isinstance(w, JalaliDateEdit):
        return w.date()
    if isinstance(w, QCheckBox):
        return w.isChecked()
    if isinstance(w, QComboBox):
        return w.currentData()
    if isinstance(w, QTextEdit):
        return w.toPlainText().strip() or None
    if isinstance(w, QLineEdit):
        return w.text().strip() or None
    return None


def set_widget_value(w: QWidget, value) -> None:
    if isinstance(w, JalaliDateEdit):
        w.setDate(value if isinstance(value, datetime.date) else datetime.date.fromisoformat(str(value)[:10]))
    elif isinstance(w, QCheckBox):
        w.setChecked(bool(value))
    elif isinstance(w, QComboBox):
        w.setCurrentIndex(max(w.findData(value), 0))
    elif isinstance(w, QTextEdit):
        w.setPlainText("" if value is None else str(value))
    elif isinstance(w, QLineEdit):
        w.setText("" if value is None else str(value))


def field_problem(f: dict, value) -> str | None:
    label = f.get("label") or f.get("key")
    if value in (None, "", []):
        return f"«{label}» را وارد کنید." if f.get("required") and f.get("kind") != "bool" else None
    if f.get("kind") in ("number", "money") and conditions._number(value) is None:
        return f"«{label}» باید عدد باشد."
    return None


class TaskFormDialog(QDialog):
    """فرم مرحله؛ decide(...) برای آزمون بدون نمایش هم قابل‌استفاده است."""

    def __init__(self, task_id: int, parent=None, main_window=None) -> None:
        super().__init__(parent)
        self.task_id = task_id
        self.main_window = main_window
        self.result_message = ""
        self.decided: str | None = None
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(900, 640)
        layout = QVBoxLayout(self)
        self.title = QLabel("")
        self.title.setObjectName("sectionTitle")
        self.title.setWordWrap(True)
        self.path = QLabel("")
        self.path.setTextFormat(Qt.RichText)
        self.path.setWordWrap(True)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setObjectName("sectionHint")
        self.instructions = QLabel("")
        self.instructions.setWordWrap(True)
        self.instructions.setObjectName("card")
        for w in (self.title, self.path, self.info, self.instructions):
            layout.addWidget(w)

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("اطلاعات سند"))
        self.context = table(["عنوان", "مقدار"])
        lv.addWidget(self.context)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(QLabel("سابقهٔ مراحل و یادداشت‌ها"))
        self.history = table(["زمان", "مرحله", "توضیح و نتیجه", "انجام‌دهنده"])
        self.history.setWordWrap(True)
        rv.addWidget(self.history)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([320, 560])
        layout.addWidget(split, stretch=1)

        self.form_box = QFrame()
        self.form_box.setObjectName("card")
        self.form = QFormLayout(self.form_box)
        self.form.setContentsMargins(12, 8, 12, 8)
        layout.addWidget(self.form_box)
        self.note = QTextEdit()
        self.note.setPlaceholderText("یادداشت یا توضیح این مرحله (برای رد و برگشت برای اصلاح الزامی است)")
        self.note.setMaximumHeight(70)
        layout.addWidget(self.note)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setObjectName("sectionHint")
        layout.addWidget(self.status)

        self.buttons: dict[str, QPushButton] = {}
        for code, label in _DECISION_BUTTONS.items():
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, d=code: self.decide(d))
            self.buttons[code] = b
        for code, label, slot in (("note", "ثبت یادداشت", self.add_note), ("open", "بازکردن سند", self.open_document),
                                  ("reassign", "ارجاع به فرد مناسب", self.reassign), ("close", "بستن فرم", self.reject)):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, f=slot: f())
            self.buttons[code] = b
        layout.addWidget(ms.footer([[self.buttons[c] for c in ("APPROVE", "DONE", "REJECT", "CHANGES")],
                                    [self.buttons["note"], self.buttons["reassign"], self.buttons["open"]],
                                    [self.buttons["close"]]]))
        self.fields: list[dict] = []
        self.field_widgets: dict[str, QWidget] = {}
        self.load()

    # --- بارگذاری ------------------------------------------------------------------------------------------
    def load(self) -> None:
        d = tasks.task_detail(company_id(), self.task_id, user_id())
        self.detail = d
        row = d.row
        self.setWindowTitle(f"{row.kind_label}: {row.title}")
        self.title.setText(P(f"{row.kind_label}: {row.title}"))
        self.path.setText(" ← ".join(f"{'✔' if s == 'done' else '●' if s == 'current' else '○'} {label}" for label, s in d.path))
        info = [f"فرایند: {row.definition_name}"] if row.definition_name else []
        if row.entity_label:
            info.append(f"سند: {row.entity_label}")
        info.append(f"درخواست‌کننده: {row.requested_by}")
        if row.due_at:
            info.append(f"مهلت: {numerals.format_jalali_datetime(row.due_at)}" + (" (گذشته)" if row.is_overdue else ""))
        info.append(f"وضعیت: {row.status_label}")
        self.info.setText(P("   |   ".join(info)))
        self.instructions.setText(P(f"چه باید کرد: {row.instructions}") if row.instructions else "")
        self.instructions.setVisible(bool(row.instructions))
        fill(self.context, [[k, v] for k, v in d.context])
        self.reload_history()
        self._build_fields(d.form_fields)
        allowed = {code for code, _l in d.decisions}
        for code, b in self.buttons.items():
            if code in _DECISION_BUTTONS:
                b.setVisible(code in allowed)
        self.buttons["note"].setEnabled(row.status_code == "OPEN")
        self.buttons["open"].setEnabled(bool(row.entity_type and row.entity_id and self.main_window is not None))
        editable = bool(allowed)
        for w in self.field_widgets.values():
            w.setEnabled(editable)
        unassigned = row.status_code == "OPEN" and any(
            t.task_id == self.task_id for t in tasks.list_unassigned(company_id(), entity_type=row.entity_type, entity_id=row.entity_id))
        self.buttons["reassign"].setVisible(unassigned and tasks.can_reassign(company_id(), user_id()))
        if unassigned:
            self.status.setText("این مرحله گیرنده ندارد؛ " + ("آن را به فرد مناسب ارجاع دهید." if self.buttons["reassign"].isVisibleTo(self)
                                                             else "مدیر باید آن را به فرد مناسب ارجاع دهد."))
        elif not editable:
            self.status.setText("این مرحله برای شما نیست یا بسته شده است؛ فقط می‌توانید آن را ببینید و یادداشت بگذارید."
                                if row.status_code == "OPEN" else f"این مرحله {row.status_label} است.")

    def reload_history(self) -> None:
        rows = runtime.timeline(company_id(), self.detail.row.instance_id) if self.detail.row.instance_id else []
        fill(self.history, [[numerals.format_jalali_datetime(r.at) if r.at else "—", r.title, r.detail, r.actor] for r in rows])
        self.history.resizeRowsToContents()

    def _build_fields(self, fields: list[dict]) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields = list(fields or [])
        self.field_widgets = {}
        for f in self.fields:
            w = field_widget(f)
            label = (f.get("label") or f.get("key")) + (" *" if f.get("required") and f.get("kind") != "bool" else "")
            self.form.addRow("" if f.get("kind") == "bool" else label, w)
            self.field_widgets[f["key"]] = w
            self._watch(f, w)
        self.form_box.setVisible(bool(self.fields))

    def _watch(self, f: dict, w: QWidget) -> None:
        def run(*_a) -> None:
            mark_invalid(w, field_problem(f, widget_value(w)))

        if isinstance(w, QComboBox):
            w.currentIndexChanged.connect(run)
        elif isinstance(w, QLineEdit):
            w.editingFinished.connect(run)
        elif isinstance(w, QTextEdit):
            w.textChanged.connect(run)

    # --- مقادیر --------------------------------------------------------------------------------------------
    def values(self) -> dict:
        return {f["key"]: widget_value(self.field_widgets[f["key"]]) for f in self.fields}

    def set_value(self, key: str, value) -> None:
        set_widget_value(self.field_widgets[key], value)

    def problems(self) -> list[str]:
        out = []
        for f in self.fields:
            w = self.field_widgets[f["key"]]
            message = field_problem(f, widget_value(w))
            mark_invalid(w, message)
            if message:
                out.append(message)
        return out

    # --- کارها ---------------------------------------------------------------------------------------------
    def decide(self, decision: str) -> bool:
        comment = self.note.toPlainText().strip()
        if decision in ("APPROVE", "DONE"):
            problems = self.problems()
            if problems:
                self.status.setText(P(" ".join(problems)))
                return False
        elif not comment and (decision == "CHANGES" or self.detail.row.kind == "APPROVAL"):
            mark_invalid(self.note, "علت را بنویسید.")
            self.status.setText("علت رد یا موارد اصلاحی را در یادداشت بنویسید.")
            self.note.setFocus()
            return False
        try:
            result = tasks.decide(company_id(), self.task_id, user_id(), decision, comment,
                                  data=self.values() if decision in ("APPROVE", "DONE") else None,
                                  row_version=self.detail.row.row_version)
        except WorkflowError as exc:
            self.status.setText(str(exc))
            return False
        self.decided = decision
        self.result_message = result.message
        self.accept()
        return True

    def add_note(self, text: str | None = None) -> bool:
        text = (self.note.toPlainText() if text is None else text).strip()
        if not text:
            mark_invalid(self.note, "متن یادداشت را بنویسید.")
            return False
        try:
            tasks.add_comment(company_id(), self.task_id, user_id(), text)
        except WorkflowError as exc:
            self.status.setText(str(exc))
            return False
        mark_invalid(self.note, None)
        self.note.clear()
        self.status.setText("یادداشت ثبت شد و برای افراد این مرحله فرستاده شد.")
        self.reload_history()
        return True

    def reassign(self, to_user_id: int | None = None) -> bool:
        """R325: مرحلهٔ بی‌گیرنده به فرد مناسب سپرده می‌شود (فقط مدیر)."""
        if to_user_id is None:
            from peecha.ui.screens.fixed_assets import FormDialog, combo
            from peecha.ui.screens.workflow_center import company_user_choices

            dlg = FormDialog("ارجاع به فرد مناسب", [("to", "انجام‌دهنده", combo(company_user_choices()))],
                             "فردی را که باید این مرحله را انجام دهد انتخاب کنید.", self)
            if dlg.exec() != QDialog.Accepted:
                return False
            to_user_id = dlg.values().get("to")
        try:
            tasks.reassign_task(company_id(), self.task_id, user_id(), [to_user_id], self.note.toPlainText().strip())
        except WorkflowError as exc:
            self.status.setText(str(exc))
            return False
        self.load()
        self.status.setText("مرحله ارجاع شد.")
        return True

    def open_document(self) -> bool:
        from peecha.ui.screens.workflow_center import open_entity

        return open_entity(self.main_window, self.detail.row.entity_type, self.detail.row.entity_id)


def run_task_form(parent, task_id: int, main_window=None) -> TaskFormDialog | None:
    """نمایش فرم مرحله؛ dialog_runner والد (در آزمون) به‌جای exec."""
    dlg = TaskFormDialog(task_id, parent, main_window)
    runner = getattr(parent, "dialog_runner", None)
    ok = runner(dlg) if runner is not None else dlg.exec() == QDialog.Accepted
    return dlg if ok or dlg.decided else None
