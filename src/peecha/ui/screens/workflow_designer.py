"""طراحیِ گردشِ کار — تعریفِ زنجیره‌ی تاییدِ کارتابل برایِ هر فرمِ برنامه.
طبقِ درخواستِ صریح («سیستمِ کارتابلِ قابلِ‌گسترش برایِ همه‌یِ ماژول‌ها»)
این صفحه رویِ کاتالوگِ عمومیِ فرم‌ها (roles_service.list_forms — همان
فرم‌هایی که در جدولِ نقش‌ها/دسترسی‌ها هم دیده می‌شوند) کار می‌کند، نه
فقط حسابداری؛ هر ماژولِ تازه که فرمش را به nav_catalog.py اضافه کند
خودکار در این فهرست هم ظاهر می‌شود."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import cartable as cartable_service
from peecha.services import roles as roles_service
from peecha.ui.widgets import FieldHelpMixin


class _StepRow(QWidget):
    def __init__(self, step_no: int, roles: list[roles_service.RoleRow], selected_role_id: int | None, on_remove) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel(f"مرحله‌ی {step_no}:"))

        self.role_combo = QComboBox()
        for role in roles:
            self.role_combo.addItem(role.code, role.role_id)
        if selected_role_id is not None:
            index = self.role_combo.findData(selected_role_id)
            if index >= 0:
                self.role_combo.setCurrentIndex(index)
        layout.addWidget(self.role_combo, stretch=1)

        remove_button = QPushButton("🗑️")
        remove_button.setObjectName("iconButton")
        remove_button.setFixedWidth(34)
        remove_button.setToolTip("حذفِ مرحله")
        remove_button.clicked.connect(lambda: on_remove(self))
        layout.addWidget(remove_button)

    def approver_role_id(self) -> int | None:
        return self.role_combo.currentData()


class WorkflowDesignerScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._step_rows: list[_StepRow] = []
        self._roles: list[roles_service.RoleRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("طراحیِ گردشِ کار")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "برایِ هر فرمِ برنامه می‌توانید زنجیره‌ای از نقش‌هایِ تاییدکننده تعریف کنید — با ثبتِ سند، به‌ترتیب "
            "به کارتابلِ هر نقش می‌رود؛ بدونِ تعریف، همان رفتارِ مستقیم (بدونِ کارتابل) باقی می‌ماند."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("فرم"))
        self.form_combo = QComboBox()
        self.form_combo.currentIndexChanged.connect(self._load_form)
        selector_row.addWidget(self.form_combo, stretch=1)
        layout.addLayout(selector_row)

        self.active_checkbox = QCheckBox("این گردشِ کار فعال باشد")
        layout.addWidget(self.active_checkbox)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

        self.steps_container = QVBoxLayout()
        steps_widget = QWidget()
        steps_widget.setLayout(self.steps_container)
        layout.addWidget(steps_widget)

        add_step_button = QPushButton("➕")
        add_step_button.setObjectName("iconButton")
        add_step_button.setFixedWidth(34)
        add_step_button.setToolTip("افزودنِ مرحله")
        add_step_button.clicked.connect(self._add_step)
        layout.addWidget(add_step_button)

        layout.addStretch(1)

        save_button = QPushButton("💾")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(40)
        save_button.setToolTip("ذخیره")
        save_button.clicked.connect(self._save)
        layout.addWidget(save_button)

        self.set_field_help([
            (
                self.form_combo,
                "با انتخابِ خالی‌گذاشتنِ همه‌ی مراحل و ذخیره، گردشِ کارِ این فرم حذف می‌شود و به حالتِ بدونِ‌کارتابل برمی‌گردد.",
            ),
        ])

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._roles = roles_service.list_roles(company_id)

        current_code = self.form_combo.currentData()
        self.form_combo.blockSignals(True)
        self.form_combo.clear()
        for form in roles_service.list_forms():
            self.form_combo.addItem(f"{form.label} ({form.module_code})", form.code)
        if current_code is not None:
            index = self.form_combo.findData(current_code)
            if index >= 0:
                self.form_combo.setCurrentIndex(index)
        self.form_combo.blockSignals(False)
        self._load_form()

    def _clear_steps(self) -> None:
        while self.steps_container.count():
            child = self.steps_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._step_rows = []

    def _load_form(self) -> None:
        self.status_label.setText("")
        self._clear_steps()
        company_id = self._company_id()
        form_code = self.form_combo.currentData()
        if company_id is None or form_code is None:
            return
        is_active, steps = cartable_service.get_workflow_steps(company_id, form_code)
        self.active_checkbox.setChecked(is_active)
        if not self._roles:
            self.status_label.setText("هیچ نقشی برایِ این شرکت تعریف نشده — ابتدا از صفحه‌ی «نقش‌ها» یک نقش بسازید.")
            return
        for step in steps:
            self._append_step_row(step.approver_role_id)

    def _append_step_row(self, selected_role_id: int | None) -> None:
        row = _StepRow(len(self._step_rows) + 1, self._roles, selected_role_id, self._remove_step)
        self.steps_container.addWidget(row)
        self._step_rows.append(row)

    def _add_step(self) -> None:
        if not self._roles:
            self.status_label.setText("هیچ نقشی برایِ این شرکت تعریف نشده — ابتدا از صفحه‌ی «نقش‌ها» یک نقش بسازید.")
            return
        self._append_step_row(None)

    def _remove_step(self, row: _StepRow) -> None:
        self._step_rows.remove(row)
        self.steps_container.removeWidget(row)
        row.deleteLater()
        for step_no, remaining_row in enumerate(self._step_rows, start=1):
            remaining_row.findChild(QLabel).setText(f"مرحله‌ی {step_no}:")

    def _save(self) -> None:
        company_id = self._company_id()
        form_code = self.form_combo.currentData()
        if company_id is None or form_code is None:
            return
        role_ids = [row.approver_role_id() for row in self._step_rows]
        if any(r is None for r in role_ids):
            self.status_label.setText("برایِ هر مرحله باید یک نقش انتخاب شود.")
            return
        cartable_service.save_workflow_steps(company_id, form_code, self.active_checkbox.isChecked(), role_ids)
        self.status_label.setText("")
        QMessageBox.information(self, "ذخیره شد", "گردشِ کار ذخیره شد.")
        self.refresh()
