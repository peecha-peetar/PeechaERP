"""مدیریتِ کاربران — معادلِ Qt برایِ users.py/.kv در Kivy."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha.services import users as users_service
from peecha.ui.widgets import FieldGrid, FieldHelpMixin, FieldSpec, LayoutEditMixin, wrap_scrollable_with_footer

_COLUMNS = ["فعال", "مدیرِ کل", "شرکت‌ها", "نامِ کامل", "نامِ کاربری"]


class UsersScreen(FieldHelpMixin, LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[users_service.UserRow] = []
        self._editing_id: int | None = None
        self._company_options: list[tuple[int, str]] = []

        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(16)
        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)

        self.set_field_help([
            (
                self.username_field,
                "نامِ کاربری برایِ ورود به سیستم. بعدِ ساختنِ کاربر قابلِ‌تغییر نیست.",
            ),
            (self.full_name_field, "نامِ کاملِ کاربر — همان‌جایی که در فهرست‌ها و رخدادنگارِ سیستم نشان داده می‌شود."),
            (self.email_field, "ایمیلِ کاربر. اختیاری است و فعلاً فقط جنبه‌یِ اطلاعاتی دارد."),
            (
                self.language_combo,
                "زبانی که رابطِ کاربری برایِ این کاربر با آن نمایش داده می‌شود.",
            ),
            (
                self.password_field,
                "رمزِ عبورِ کاربر. برایِ کاربرِ تازه اجباری است و باید حداقل ۶ کاراکتر باشد. "
                "هنگامِ ویرایش، اگر خالی بگذارید رمزِ قبلی همان‌طور می‌ماند.",
            ),
            (
                self.is_super_admin_checkbox,
                "مدیرِ کلِ سیستم است یا نه. این وضعیت معمولاً فقط برایِ کاربرِ اولِ سیستم استفاده می‌شود.",
            ),
            (
                self.is_active_checkbox,
                "کاربرِ غیرِفعال دیگر نمی‌تواند وارد سیستم شود. حساب و سابقه‌اش پاک نمی‌شود.",
            ),
            (
                self.company_list,
                "این کاربر به کدام شرکت‌ها دسترسی دارد را تیک بزنید. سیستم چندشرکتی است و هر کاربر فقط "
                "شرکت‌هایِ تیک‌خورده را در انتخابِ شرکتِ بالایِ برنامه می‌بیند.",
            ),
            (
                self.default_company_combo,
                "شرکتی که هنگامِ ورود به سیستم به‌طورِ پیش‌فرض برایِ این کاربر انتخاب می‌شود.",
            ),
        ])

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("کاربران")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table)
        return panel

    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)

        self.form_title = QLabel("کاربرِ جدید")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        self.username_field = QLineEdit()

        self.full_name_field = QLineEdit()

        self.email_field = QLineEdit()

        self.language_combo = QComboBox()

        self.password_field = QLineEdit()
        self.password_field.setEchoMode(QLineEdit.Password)
        self.password_field.setPlaceholderText("(برایِ عدمِ تغییر، خالی بگذارید)")

        self.is_super_admin_checkbox = QCheckBox("مدیرِ کلِ سیستم")

        self.is_active_checkbox = QCheckBox("فعال")
        self.is_active_checkbox.setChecked(True)

        self.basic_grid = FieldGrid([
            FieldSpec("username", "نامِ کاربری", self.username_field, span=1),
            FieldSpec("full_name", "نامِ کامل", self.full_name_field, span=2),
            FieldSpec("email", "ایمیل", self.email_field, span=3),
            FieldSpec("language", "زبانِ پیش‌فرض", self.language_combo, span=1),
            FieldSpec("password", "رمزِ عبور", self.password_field, span=2),
            FieldSpec("is_super_admin", "", self.is_super_admin_checkbox, span=1),
            FieldSpec("is_active", "", self.is_active_checkbox, span=1),
        ])
        layout.addWidget(self.basic_grid)
        self.register_field_grids("users", [self.basic_grid])

        layout.addWidget(QLabel("دسترسی به شرکت‌ها"))
        self.company_list = QListWidget()
        self.company_list.setMaximumHeight(120)
        layout.addWidget(self.company_list)

        grid2 = QGridLayout()
        grid2.addWidget(QLabel("شرکتِ پیش‌فرض"), 0, 0)
        self.default_company_combo = QComboBox()
        grid2.addWidget(self.default_company_combo, 0, 1)
        layout.addLayout(grid2)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        save_button = QPushButton("💾")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(48)
        save_button.setToolTip("ذخیره")
        save_button.clicked.connect(self._save)

        cancel_button = QPushButton("↩️")
        cancel_button.setObjectName("iconButton")
        cancel_button.setFixedWidth(44)
        cancel_button.setToolTip("انصراف")
        cancel_button.clicked.connect(self._reset_form)

        layout.addStretch(1)
        return wrap_scrollable_with_footer(panel, [save_button, cancel_button])

    def refresh(self) -> None:
        self._company_options = users_service.list_companies_for_picker()
        self._language_options = users_service.list_languages_for_picker()

        self.language_combo.clear()
        self.language_combo.addItem("—", None)
        for lang_id, name in self._language_options:
            self.language_combo.addItem(name, lang_id)

        self._reset_form()
        self._rows = users_service.list_users()
        self.table.setRowCount(len(self._rows))
        company_names = dict(self._company_options)
        for row_index, user in enumerate(self._rows):
            company_labels = "، ".join(company_names.get(cid, "?") for cid in user.company_ids)
            values = [
                "بله" if user.is_active else "خیر",
                "بله" if user.is_super_admin else "خیر",
                company_labels or "—",
                user.full_name,
                user.username,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, user.user_id)
                self.table.setItem(row_index, col_index, item)

    def _rebuild_company_widgets(self, selected_ids: set[int] | None = None) -> None:
        selected_ids = selected_ids or set()
        self.company_list.clear()
        for company_id, name in self._company_options:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if company_id in selected_ids else Qt.Unchecked)
            item.setData(Qt.UserRole, company_id)
            self.company_list.addItem(item)

        self.default_company_combo.clear()
        self.default_company_combo.addItem("—", None)
        for company_id, name in self._company_options:
            if company_id in selected_ids or not selected_ids:
                self.default_company_combo.addItem(name, company_id)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        user_id = self.table.item(row, 0).data(Qt.UserRole)
        user = next((r for r in self._rows if r.user_id == user_id), None)
        if user is not None:
            self._load_into_form(user)

    def _load_into_form(self, user: users_service.UserRow) -> None:
        self._editing_id = user.user_id
        self.form_title.setText(f"ویرایشِ کاربر — {user.username}")
        self.status_label.setText("")
        self.username_field.setText(user.username)
        self.username_field.setEnabled(False)
        self.full_name_field.setText(user.full_name)
        self.email_field.setText(user.email or "")
        self.password_field.clear()
        if user.default_language_id is not None:
            index = self.language_combo.findData(user.default_language_id)
            self.language_combo.setCurrentIndex(index if index >= 0 else 0)
        else:
            self.language_combo.setCurrentIndex(0)
        self.is_super_admin_checkbox.setChecked(user.is_super_admin)
        self.is_active_checkbox.setChecked(user.is_active)
        self._rebuild_company_widgets(set(user.company_ids))
        if user.default_company_id is not None:
            index = self.default_company_combo.findData(user.default_company_id)
            self.default_company_combo.setCurrentIndex(index if index >= 0 else 0)

    def _reset_form(self) -> None:
        self._editing_id = None
        self.form_title.setText("کاربرِ جدید")
        self.status_label.setText("")
        self.username_field.clear()
        self.username_field.setEnabled(True)
        self.full_name_field.clear()
        self.email_field.clear()
        self.password_field.clear()
        self.language_combo.setCurrentIndex(0)
        self.is_super_admin_checkbox.setChecked(False)
        self.is_active_checkbox.setChecked(True)
        self._rebuild_company_widgets(set())
        self.table.clearSelection()

    def _selected_company_ids(self) -> list[int]:
        ids = []
        for i in range(self.company_list.count()):
            item = self.company_list.item(i)
            if item.checkState() == Qt.Checked:
                ids.append(item.data(Qt.UserRole))
        return ids

    def _save(self) -> None:
        full_name = self.full_name_field.text().strip()
        if not full_name:
            self.status_label.setText("نامِ کامل را وارد کنید.")
            return

        email = self.email_field.text().strip() or None
        language_id = self.language_combo.currentData()
        is_super_admin = self.is_super_admin_checkbox.isChecked()
        is_active = self.is_active_checkbox.isChecked()
        company_ids = self._selected_company_ids()
        default_company_id = self.default_company_combo.currentData()
        password = self.password_field.text()

        try:
            if self._editing_id is not None:
                users_service.update_user(
                    self._editing_id,
                    full_name,
                    email,
                    language_id,
                    is_super_admin,
                    is_active,
                    company_ids,
                    default_company_id,
                    new_password=password or None,
                )
            else:
                username = self.username_field.text().strip()
                if not username:
                    self.status_label.setText("نامِ کاربری را وارد کنید.")
                    return
                if len(password) < 6:
                    self.status_label.setText("رمزِ عبور باید حداقل ۶ کاراکتر باشد.")
                    return
                users_service.create_user(
                    username,
                    full_name,
                    password,
                    email,
                    language_id,
                    is_super_admin,
                    company_ids,
                    default_company_id,
                )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return

        self.refresh()
