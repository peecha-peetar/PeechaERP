"""نقش‌ها و دسترسی‌ها — معادلِ Qt برایِ roles.py/.kv در Kivy."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import roles as roles_service
from peecha.ui.widgets import FieldHelpMixin

_ACTIONS = ["VIEW", "CREATE", "EDIT", "DELETE"]


class RolesScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._roles: list[roles_service.RoleRow] = []
        self._forms: list[roles_service.FormOption] = []
        self._editing_role_id: int | None = None
        self._permission_checkboxes: dict[tuple[int, str], QCheckBox] = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)
        outer.addWidget(self._build_roles_panel(), stretch=1)
        outer.addWidget(self._build_detail_panel(), stretch=3)

        self.set_field_help([
            (self.role_list, "فهرستِ نقش‌هایِ این شرکت. برایِ دیدن و تغییرِ دسترسی‌هایِ هر نقش، رویِ آن کلیک کنید."),
            (self.new_role_code_field, "کدِ نقشِ تازه، مثلاً «حسابدار» یا «انباردار». بعدِ ساختن قابلِ‌تغییر نیست."),
            (
                self.parent_role_combo,
                "نقشِ والد فقط برایِ سازمان‌دهی و نمایشِ سلسله‌مراتب است. "
                "دسترسی‌هایِ هر نقش را باید جداگانه مشخص کنید — از والد به‌طورِ خودکار ارث نمی‌رسد.",
            ),
            (
                self.is_active_checkbox,
                "نقشِ غیرِفعال دیگر قابلِ‌تخصیص به کاربرانِ تازه نیست. کاربرانی که از قبل این نقش را دارند تحتِ‌تأثیر قرار نمی‌گیرند.",
            ),
            (
                self.permission_table,
                "برایِ هر فرمِ برنامه مشخص کنید این نقش اجازه‌یِ دیدن (VIEW)، ساختن (CREATE)، ویرایش (EDIT) "
                "یا حذف (DELETE) را دارد یا نه. هر کاربرِ دارایِ این نقش، فقط همین دسترسی‌ها را می‌گیرد.",
            ),
            (
                self.users_list,
                "کاربرانی که این نقش را دارند تیک‌خورده‌اند. با تیک‌زدن یا برداشتنِ تیک، نقش را به کاربر می‌دهید یا از او می‌گیرید.",
            ),
        ])

    def _build_roles_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("نقش‌ها")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.role_list = QListWidget()
        self.role_list.itemClicked.connect(self._on_role_selected)
        layout.addWidget(self.role_list)

        layout.addWidget(QLabel("کدِ نقشِ جدید"))
        self.new_role_code_field = QLineEdit()
        layout.addWidget(self.new_role_code_field)

        layout.addWidget(QLabel("والد (اختیاری)"))
        self.parent_role_combo = QComboBox()
        layout.addWidget(self.parent_role_combo)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        create_button = QPushButton("افزودنِ نقش")
        create_button.setObjectName("primaryButton")
        create_button.clicked.connect(self._create_role)
        layout.addWidget(create_button)

        self.is_active_checkbox = QCheckBox("فعال")
        self.is_active_checkbox.setChecked(True)
        self.is_active_checkbox.toggled.connect(self._on_active_toggled)
        layout.addWidget(self.is_active_checkbox)

        layout.addStretch(1)
        return panel

    def _build_detail_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.detail_title = QLabel("یک نقش را از فهرست انتخاب کنید")
        self.detail_title.setObjectName("pageTitle")
        layout.addWidget(self.detail_title)

        tabs = QTabWidget()
        layout.addWidget(tabs, stretch=1)

        self.permission_table = QTableWidget(0, 1 + len(_ACTIONS))
        self.permission_table.setHorizontalHeaderLabels(["فرم"] + _ACTIONS)
        self.permission_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.permission_table.verticalHeader().setVisible(False)
        self.permission_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        tabs.addTab(self.permission_table, "دسترسیِ فرم‌ها")

        self.users_list = QListWidget()
        tabs.addTab(self.users_list, "کاربرانِ این نقش")

        return panel

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        self._forms = roles_service.list_forms()
        company_id = self._company_id()
        self._roles = roles_service.list_roles(company_id) if company_id is not None else []

        self.role_list.clear()
        for role in self._roles:
            item = QListWidgetItem(role.code + ("" if role.is_active else " (غیرفعال)"))
            item.setData(Qt.UserRole, role.role_id)
            self.role_list.addItem(item)

        self.parent_role_combo.clear()
        self.parent_role_combo.addItem("— بدونِ والد —", None)
        for role in self._roles:
            self.parent_role_combo.addItem(role.code, role.role_id)

        self._editing_role_id = None
        self.detail_title.setText("یک نقش را از فهرست انتخاب کنید")
        self.permission_table.setRowCount(0)
        self.users_list.clear()

    def _on_role_selected(self, item: QListWidgetItem) -> None:
        role_id = item.data(Qt.UserRole)
        role = next((r for r in self._roles if r.role_id == role_id), None)
        if role is None:
            return
        self._editing_role_id = role_id
        self.detail_title.setText(f"نقش: {role.code}")
        self.is_active_checkbox.blockSignals(True)
        self.is_active_checkbox.setChecked(role.is_active)
        self.is_active_checkbox.blockSignals(False)
        self._render_permission_table(role_id)
        self._render_users_list(role_id)

    def _render_permission_table(self, role_id: int) -> None:
        allowed = roles_service.get_role_permissions(role_id)
        self._permission_checkboxes = {}
        self.permission_table.setRowCount(len(self._forms))
        for row_index, form in enumerate(self._forms):
            label_item = QTableWidgetItem(f"{form.label} ({form.module_code})")
            self.permission_table.setItem(row_index, 0, label_item)
            for col_index, action_code in enumerate(_ACTIONS, start=1):
                checkbox = QCheckBox()
                checkbox.setChecked((form.form_id, action_code) in allowed)
                checkbox.toggled.connect(
                    lambda checked, fid=form.form_id, ac=action_code: self._toggle_permission(fid, ac, checked)
                )
                self.permission_table.setCellWidget(row_index, col_index, checkbox)
                self._permission_checkboxes[(form.form_id, action_code)] = checkbox

    def _toggle_permission(self, form_id: int, action_code: str, checked: bool) -> None:
        if self._editing_role_id is None:
            return
        roles_service.set_role_permission(self._editing_role_id, form_id, action_code, checked)

    def _render_users_list(self, role_id: int) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self.users_list.clear()
        for row in roles_service.list_role_users(role_id, company_id):
            item = QListWidgetItem(row.full_name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if row.assigned else Qt.Unchecked)
            item.setData(Qt.UserRole, row.user_id)
            self.users_list.addItem(item)
        self.users_list.itemChanged.connect(self._on_user_assignment_changed)

    def _on_user_assignment_changed(self, item: QListWidgetItem) -> None:
        if self._editing_role_id is None:
            return
        company_id = self._company_id()
        if company_id is None:
            return
        user_id = item.data(Qt.UserRole)
        roles_service.set_user_role(user_id, self._editing_role_id, company_id, item.checkState() == Qt.Checked)

    def _on_active_toggled(self, checked: bool) -> None:
        if self._editing_role_id is None:
            return
        company_id = self._company_id()
        if company_id is None:
            return
        role = next((r for r in self._roles if r.role_id == self._editing_role_id), None)
        if role is None:
            return
        try:
            roles_service.update_role(self._editing_role_id, company_id, role.parent_role_id, checked)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()

    def _create_role(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            self.status_label.setText("ابتدا یک شرکت را انتخاب کنید.")
            return
        code = self.new_role_code_field.text().strip()
        if not code:
            self.status_label.setText("کدِ نقش را وارد کنید.")
            return
        try:
            roles_service.create_role(company_id, code, self.parent_role_combo.currentData())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("")
        self.new_role_code_field.clear()
        self.refresh()
