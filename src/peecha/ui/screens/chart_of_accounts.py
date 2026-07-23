"""کدینگِ حساب‌ها — معادلِ Qt برایِ chart_of_accounts.py/.kv در Kivy.

فهرست (چپ) + فرمِ ساخت/ویرایش (راست، طبقِ ترتیبِ RTLِ Qt، «راست» یعنی
اولین‌اعلام‌شده در QHBoxLayout, بر خلافِ Kivy که نیاز به ترتیبِ معکوس
داشت)."""

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
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.ui import theme
from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service

_NATURE_OPTIONS = [("DEBIT", "بدهکار"), ("CREDIT", "بستانکار"), ("BOTH", "دوطرفه")]
_CATEGORY_OPTIONS = [
    ("ASSET", "دارایی"), ("LIABILITY", "بدهی"), ("EQUITY", "حقوق صاحبان سهام"),
    ("REVENUE", "درآمد"), ("EXPENSE", "هزینه"),
]
_ACCOUNT_TYPE_OPTIONS = [("PERMANENT", "ترازنامه‌ای"), ("TEMPORARY", "موقت")]
_LEVEL_LABELS = {1: "گروه", 2: "کل", 3: "معین"}
_LEVEL_COLORS = {1: theme.LEVEL_GROUP, 2: theme.LEVEL_KOL, 3: theme.LEVEL_MOEIN}

_COLUMNS = ["فعال؟", "قابلِ ثبت", "سطح", "نام", "کدِ کامل"]


def _fill_combo(combo: QComboBox, options: list[tuple[str, str]]) -> None:
    combo.clear()
    for code, label in options:
        combo.addItem(label, code)


def _combo_value(combo: QComboBox) -> str | None:
    return combo.currentData()


def _select_combo_value(combo: QComboBox, value: str | None) -> None:
    if value is None:
        combo.setCurrentIndex(0)
        return
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else 0)


class ChartOfAccountsScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[coa_service.AccountRow] = []
        self._editing_account_id: int | None = None
        self._parent_options: list[coa_service.AccountRow] = []

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        outer.addWidget(self._build_list_panel(), stretch=3)
        outer.addWidget(self._build_form_panel(), stretch=2)

    # --- فهرست --------------------------------------------------------------
    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("کدینگِ حساب‌ها")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("جستجو در کد یا نامِ حساب")
        self.search_field.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search_field)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        layout.addWidget(self.table)

        return panel

    # --- فرم ------------------------------------------------------------
    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.form_title = QLabel("حسابِ جدید")
        self.form_title.setObjectName("pageTitle")
        layout.addWidget(self.form_title)

        grid = QGridLayout()
        grid.setSpacing(8)
        row = 0

        grid.addWidget(QLabel("والد"), row, 0)
        self.parent_combo = QComboBox()
        self.parent_combo.currentIndexChanged.connect(self._update_level_preview)
        grid.addWidget(self.parent_combo, row, 1)
        row += 1

        grid.addWidget(QLabel("کدِ بخش"), row, 0)
        self.segment_code_field = QLineEdit()
        grid.addWidget(self.segment_code_field, row, 1)
        row += 1

        grid.addWidget(QLabel("نام"), row, 0)
        self.name_field = QLineEdit()
        grid.addWidget(self.name_field, row, 1)
        row += 1

        grid.addWidget(QLabel("ماهیت"), row, 0)
        self.nature_combo = QComboBox()
        _fill_combo(self.nature_combo, _NATURE_OPTIONS)
        grid.addWidget(self.nature_combo, row, 1)
        row += 1

        grid.addWidget(QLabel("دسته"), row, 0)
        self.category_combo = QComboBox()
        _fill_combo(self.category_combo, _CATEGORY_OPTIONS)
        grid.addWidget(self.category_combo, row, 1)
        row += 1

        grid.addWidget(QLabel("نوعِ حساب"), row, 0)
        self.account_type_combo = QComboBox()
        _fill_combo(self.account_type_combo, _ACCOUNT_TYPE_OPTIONS)
        grid.addWidget(self.account_type_combo, row, 1)
        row += 1

        self.is_postable_checkbox = QCheckBox("قابلِ ثبتِ سند")
        self.is_postable_checkbox.toggled.connect(self._update_dimension_checklists_visibility)
        grid.addWidget(self.is_postable_checkbox, row, 1)
        row += 1

        layout.addLayout(grid)

        self.level_preview_label = QLabel("")
        self.level_preview_label.setObjectName("sectionHint")
        layout.addWidget(self.level_preview_label)

        # طبقِ درخواستِ صریح: در فرمِ حسابِ سطحِ آخر (قابلِ ثبتِ سند)، فهرستِ
        # نوع‌بُعدهایِ تفصیلی + گروه‌هایِ اشخاصِ مجاز نمایش داده می‌شود تا
        # مشخص شود کدام‌ها به این معین مرتبط‌اند — فقط برایِ حسابِ
        # از-قبل-ذخیره‌شده (چون ذخیره‌شان به account_id نیاز دارد).
        self.dimension_types_label = QLabel("نوع‌بُعدهایِ تفصیلیِ الزامی")
        self.dimension_types_label.setObjectName("sectionHint")
        layout.addWidget(self.dimension_types_label)
        self.dimension_types_list = QListWidget()
        self.dimension_types_list.setMaximumHeight(110)
        layout.addWidget(self.dimension_types_list)

        self.person_groups_label = QLabel("گروهِ تفصیلیِ اشخاصِ مجاز (هیچ‌کدام = آزاد)")
        self.person_groups_label.setObjectName("sectionHint")
        layout.addWidget(self.person_groups_label)
        self.person_groups_list = QListWidget()
        self.person_groups_list.setMaximumHeight(90)
        layout.addWidget(self.person_groups_list)

        self.save_dimensions_button = QPushButton("ذخیره‌ی نوع‌هایِ تفصیلی")
        self.save_dimensions_button.setObjectName("flatButton")
        self.save_dimensions_button.clicked.connect(self._save_dimensions)
        layout.addWidget(self.save_dimensions_button)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

        buttons_layout = QHBoxLayout()
        self.save_button = QPushButton("ذخیره")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save)
        buttons_layout.addWidget(self.save_button)

        cancel_button = QPushButton("انصراف")
        cancel_button.setObjectName("flatButton")
        cancel_button.clicked.connect(self._reset_form)
        buttons_layout.addWidget(cancel_button)

        self.delete_button = QPushButton("حذف")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self._delete)
        self.delete_button.setVisible(False)
        buttons_layout.addWidget(self.delete_button)

        layout.addLayout(buttons_layout)
        layout.addStretch(1)

        return panel

    # --- بارگذاری/فیلتر --------------------------------------------------
    def refresh(self) -> None:
        self._reset_form()
        company_id = self._company_id()
        self._rows = coa_service.list_accounts(company_id) if company_id is not None else []
        self._reload_parent_options()
        self._apply_filter()

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def _reload_parent_options(self) -> None:
        self._parent_options = [r for r in self._rows if r.account_level < coa_service.MAX_ACCOUNT_LEVEL]
        self.parent_combo.blockSignals(True)
        self.parent_combo.clear()
        self.parent_combo.addItem("— بدونِ والد (سطحِ گروه) —", None)
        for account in self._parent_options:
            self.parent_combo.addItem(f"{account.full_code} — {account.name}", account.account_id)
        self.parent_combo.blockSignals(False)
        self._update_level_preview()

    def _apply_filter(self) -> None:
        query = self.search_field.text().strip()
        filtered = [r for r in self._rows if not query or query in r.full_code or query in r.name]
        self.table.setRowCount(len(filtered))
        for row_index, account in enumerate(filtered):
            values = [
                "فعال" if True else "",  # حساب‌ها فیلدِ is_active ندارند در این نسخه؛ جایگزین: قابلِ‌ثبت
                "بله" if account.is_postable else "خیر",
                _LEVEL_LABELS[account.account_level],
                account.name,
                account.full_code,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, account.account_id)
                if col_index == 3:
                    item.setForeground(_hex_to_qcolor(_LEVEL_COLORS[account.account_level]))
                self.table.setItem(row_index, col_index, item)

    def _on_row_selected(self) -> None:
        selected = self.table.selectedItems()
        if not selected:
            return
        account_id = selected[0].data(Qt.UserRole)
        row = next((r for r in self._rows if r.account_id == account_id), None)
        if row is not None:
            self._load_into_form(row)

    # --- فرم: بارگذاری/ذخیره/حذف -----------------------------------------
    def _load_into_form(self, account: coa_service.AccountRow) -> None:
        self._editing_account_id = account.account_id
        self.form_title.setText(f"ویرایشِ حساب — {account.full_code}")
        self.status_label.setText("")
        self.level_preview_label.setVisible(False)
        self.name_field.setText(account.name)
        _select_combo_value(self.nature_combo, account.nature_code)
        _select_combo_value(self.category_combo, account.category_code)
        _select_combo_value(self.account_type_combo, account.account_type_code)
        self.is_postable_checkbox.setChecked(account.is_postable)
        self.segment_code_field.setText(account.full_code.rsplit("-", 1)[-1])
        self.segment_code_field.setEnabled(False)
        self.parent_combo.setEnabled(False)
        self.delete_button.setVisible(True)

        # طبقِ درخواستِ صریح: فقط سطحِ آخر (معین) می‌تواند قابلِ ثبتِ سند
        # باشد.
        is_leaf_level = account.account_level == coa_service.MAX_ACCOUNT_LEVEL
        self.is_postable_checkbox.setEnabled(is_leaf_level)

        # طبقِ درخواستِ صریح: حسابی که سندی رویش ثبت شده، اصلاً قابلِ‌ویرایش
        # نیست.
        locked = coa_service.account_has_posted_lines(account.account_id)
        for widget in (self.name_field, self.nature_combo, self.category_combo, self.account_type_combo):
            widget.setEnabled(not locked)
        if locked:
            self.is_postable_checkbox.setEnabled(False)
        self.delete_button.setEnabled(not locked)
        self.save_button.setEnabled(not locked)
        if locked:
            self.status_label.setObjectName("sectionHint")
            self.status_label.setStyleSheet("")
            self.status_label.setText("این حساب در سندهای حسابداری استفاده شده؛ قابلِ‌ویرایش نیست.")

        self._populate_dimension_checklists(account.account_id if is_leaf_level else None)
        self._update_dimension_checklists_visibility()

    def _reset_form(self) -> None:
        self._editing_account_id = None
        self.form_title.setText("حسابِ جدید")
        self.status_label.setText("")
        self.segment_code_field.clear()
        self.segment_code_field.setEnabled(True)
        self.parent_combo.setEnabled(True)
        self.parent_combo.setCurrentIndex(0)
        self.name_field.clear()
        for widget in (self.name_field, self.nature_combo, self.category_combo, self.account_type_combo):
            widget.setEnabled(True)
        self.nature_combo.setCurrentIndex(0)
        self.category_combo.setCurrentIndex(0)
        self.account_type_combo.setCurrentIndex(0)
        self.is_postable_checkbox.setEnabled(True)
        self.is_postable_checkbox.setChecked(False)
        self.delete_button.setVisible(False)
        self.delete_button.setEnabled(True)
        self.save_button.setEnabled(True)
        self.level_preview_label.setVisible(True)
        self.table.clearSelection()
        self._populate_dimension_checklists(None)
        self._update_dimension_checklists_visibility()

    def _update_level_preview(self) -> None:
        parent_id = self.parent_combo.currentData()
        if parent_id is None:
            level = 1
        else:
            parent = next((r for r in self._parent_options if r.account_id == parent_id), None)
            level = (parent.account_level + 1) if parent is not None else 1
        self.level_preview_label.setText(f"سطحِ حسابِ جدید: {_LEVEL_LABELS[level]}")
        if self._editing_account_id is None:
            is_leaf_level = level == coa_service.MAX_ACCOUNT_LEVEL
            self.is_postable_checkbox.setEnabled(is_leaf_level)
            if not is_leaf_level:
                self.is_postable_checkbox.setChecked(False)

    # --- چک‌لیستِ نوع‌بُعدهایِ تفصیلی/گروه‌هایِ اشخاصِ مجاز -------------------
    def _update_dimension_checklists_visibility(self) -> None:
        visible = self._editing_account_id is not None and self.is_postable_checkbox.isChecked()
        for widget in (
            self.dimension_types_label,
            self.dimension_types_list,
            self.person_groups_label,
            self.person_groups_list,
            self.save_dimensions_button,
        ):
            widget.setVisible(visible)

    def _populate_dimension_checklists(self, account_id: int | None) -> None:
        company_id = self._company_id()
        self.dimension_types_list.clear()
        self.person_groups_list.clear()
        if company_id is None:
            return

        required_type_ids = set(dimensions_service.get_account_dimension_type_ids(account_id)) if account_id else set()
        for dim in dimensions_service.list_active_dimension_types(company_id):
            item = QListWidgetItem(dim.code)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if dim.dimension_type_id in required_type_ids else Qt.Unchecked)
            item.setData(Qt.UserRole, dim.dimension_type_id)
            self.dimension_types_list.addItem(item)

        required_group_ids = set(dimensions_service.get_account_person_group_ids(account_id)) if account_id else set()
        for group in dimensions_service.list_person_groups(company_id):
            item = QListWidgetItem(group.name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if group.person_group_id in required_group_ids else Qt.Unchecked)
            item.setData(Qt.UserRole, group.person_group_id)
            self.person_groups_list.addItem(item)

    def _save_dimensions(self) -> None:
        if self._editing_account_id is None:
            return
        company_id = self._company_id()
        if company_id is None:
            return
        dimension_type_ids = [
            self.dimension_types_list.item(i).data(Qt.UserRole)
            for i in range(self.dimension_types_list.count())
            if self.dimension_types_list.item(i).checkState() == Qt.Checked
        ]
        person_group_ids = [
            self.person_groups_list.item(i).data(Qt.UserRole)
            for i in range(self.person_groups_list.count())
            if self.person_groups_list.item(i).checkState() == Qt.Checked
        ]
        try:
            dimensions_service.set_account_dimension_types(self._editing_account_id, company_id, dimension_type_ids)
            dimensions_service.set_account_person_groups(self._editing_account_id, company_id, person_group_ids)
        except ValueError as exc:
            self.status_label.setObjectName("statusError")
            self.status_label.setStyleSheet("")
            self.status_label.setText(str(exc))
            return
        self.status_label.setObjectName("statusOk")
        self.status_label.setStyleSheet("")
        self.status_label.setText("نوع‌هایِ تفصیلی ذخیره شد.")

    def _current_language_id(self) -> int | None:
        return session.current_company.default_language_id if session.current_company else None

    def _save(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            self.status_label.setText("ابتدا یک شرکت را انتخاب کنید.")
            return

        name = self.name_field.text().strip()
        nature_code = _combo_value(self.nature_combo)
        category_code = _combo_value(self.category_combo)
        account_type_code = _combo_value(self.account_type_combo)
        is_postable = self.is_postable_checkbox.isChecked()

        if not name:
            self.status_label.setText("نام را وارد کنید.")
            return

        try:
            if self._editing_account_id is not None:
                coa_service.update_account(
                    self._editing_account_id,
                    company_id,
                    name,
                    nature_code,
                    category_code,
                    account_type_code,
                    is_postable,
                    self._current_language_id(),
                    changed_by_user_id=session.current_user.user_id if session.current_user else None,
                )
            else:
                segment_code = self.segment_code_field.text().strip()
                if not segment_code:
                    self.status_label.setText("کدِ بخش را وارد کنید.")
                    return
                coa_service.create_account(
                    company_id,
                    segment_code,
                    name,
                    nature_code,
                    category_code,
                    account_type_code,
                    is_postable,
                    self._current_language_id(),
                    parent_account_id=self.parent_combo.currentData(),
                    changed_by_user_id=session.current_user.user_id if session.current_user else None,
                )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return

        self.refresh()

    def _delete(self) -> None:
        if self._editing_account_id is None:
            return
        company_id = self._company_id()
        if company_id is None:
            return
        confirm = QMessageBox.question(
            self, "حذفِ حساب", "این حساب حذف شود؟", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            coa_service.delete_account(
                self._editing_account_id,
                company_id,
                changed_by_user_id=session.current_user.user_id if session.current_user else None,
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()


def _hex_to_qcolor(hex_code: str):
    from PySide6.QtGui import QColor

    return QColor(hex_code)
