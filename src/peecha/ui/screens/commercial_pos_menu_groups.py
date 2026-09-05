"""گروه‌هایِ POS (مرحلهٔ ۹) — گروه‌بندیِ کاملاً مستقل از دسته‌بندیِ عمومیِ
انبار (inv.item_categories)، فقط برایِ چیدمانِ تب‌هایِ دسترسیِ‌سریعِ
صفحه‌یِ فروشِ حضوری. طبقِ بازخوردِ صریح («کالا باید یک فیلدِ
دسته‌بندیِ مخصوصِ POS داشته باشد که با دسته‌بندی‌هایِ دیگر فرق کند»).

طبقِ بازخوردِ صریحِ دیگر («منویِ تازه اضافه نکن»)، این ویجت دیگر یک
صفحه/مسیرِ ناوبریِ مستقل نیست -- به‌عنوانِ یک تب («تک‌فروشی») درونِ
صفحه‌یِ تنظیماتِ فاکتورِ صندوق (commercial_pos_sessions.py) جاسازی
می‌شود."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.services import commercial_pos as pos_service
from peecha.ui.widgets import wrap_scrollable


class CommercialPosMenuGroupsScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._groups: list = []
        self._editing_id: int | None = None

        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(10)

        title = QLabel("گروه‌هایِ POS (تب‌هایِ دسترسیِ‌سریعِ صفحه‌یِ فروش)")
        title.setObjectName("sectionTitle")
        outer.addWidget(title)

        hint = QLabel(
            "این گروه‌بندی کاملاً مستقل از دسته‌بندیِ عمومیِ کالاست -- فقط تعیین می‌کند هر کالا "
            "در کدام تبِ دسترسیِ‌سریعِ صفحه‌یِ «فروشِ حضوری» نمایش داده شود. (خودِ گروه به هر کالا "
            "از تبِ POS در فرمِ کالا اختصاص داده می‌شود.)"
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["نام", "ترتیب", "فعال"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        outer.addWidget(self.table)

        form_row = QHBoxLayout()
        self.name_field = QLineEdit()
        self.name_field.setPlaceholderText("نامِ گروه")
        form_row.addWidget(self.name_field, stretch=1)
        form_row.addWidget(QLabel("ترتیب"))
        self.order_field = QSpinBox()
        self.order_field.setRange(0, 999)
        form_row.addWidget(self.order_field)
        self.active_checkbox = QCheckBox("فعال")
        self.active_checkbox.setChecked(True)
        form_row.addWidget(self.active_checkbox)
        save_button = QPushButton("💾")
        save_button.setObjectName("primaryIconButton")
        save_button.setFixedWidth(48)
        save_button.setToolTip("ذخیره")
        save_button.clicked.connect(self._save)
        form_row.addWidget(save_button)
        new_button = QPushButton("🆕")
        new_button.setObjectName("iconButton")
        new_button.setFixedWidth(44)
        new_button.setToolTip("گروهِ تازه")
        new_button.clicked.connect(self._reset_form)
        form_row.addWidget(new_button)
        delete_button = QPushButton("🗑️")
        delete_button.setObjectName("dangerIconButton")
        delete_button.setFixedWidth(44)
        delete_button.setToolTip("حذف")
        delete_button.clicked.connect(self._delete)
        form_row.addWidget(delete_button)
        outer.addLayout(form_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)
        outer.addStretch(1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(wrap_scrollable(page))

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._groups = pos_service.list_menu_groups(company_id)
        self.table.setRowCount(len(self._groups))
        for row_index, g in enumerate(self._groups):
            values = [g.name, str(g.display_order), "بله" if g.is_active else "خیر"]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, g.group_id)
                self.table.setItem(row_index, col_index, item)
        self._reset_form()

    def _on_row_clicked(self, row: int, _column: int) -> None:
        group = self._groups[row]
        self._editing_id = group.group_id
        self.name_field.setText(group.name)
        self.order_field.setValue(group.display_order)
        self.active_checkbox.setChecked(group.is_active)
        self.status_label.setText("")

    def _reset_form(self) -> None:
        self._editing_id = None
        self.name_field.clear()
        self.order_field.setValue(0)
        self.active_checkbox.setChecked(True)
        self.status_label.setText("")
        self.table.clearSelection()

    def _save(self) -> None:
        company_id = self._company_id()
        name = self.name_field.text().strip()
        try:
            if self._editing_id is not None:
                pos_service.update_menu_group(
                    self._editing_id, company_id, name, self.order_field.value(), self.active_checkbox.isChecked(),
                )
            else:
                pos_service.create_menu_group(company_id, name, self.order_field.value())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()

    def _delete(self) -> None:
        if self._editing_id is None:
            self.status_label.setText("یک گروه را از فهرست انتخاب کنید.")
            return
        confirm = QMessageBox.question(self, "حذفِ گروه", "این گروه حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            pos_service.delete_menu_group(self._editing_id, self._company_id())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
