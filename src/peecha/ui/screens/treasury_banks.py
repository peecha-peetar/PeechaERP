"""فهرستِ مرجعِ نام‌هایِ بانک — طبقِ درخواستِ صریح: «نام بانک اگر لیستی
باشه ... در فرمی جدا تعریف بشه بهتره» — برایِ انتخاب در فیلدِ «بانکِ
صادرکننده»یِ فرمِ ثبتِ چکِ دریافتی، به‌جایِ تایپِ آزادِ نام."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import treasury as treasury_service
from peecha.ui.widgets import FieldHelpMixin, wrap_scrollable


class TreasuryBanksScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.company_id: int | None = None
        self._editing_bank_id: int | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("بانک‌ها")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

        add_row = QHBoxLayout()
        self.code_field = QLineEdit()
        self.code_field.setPlaceholderText("کد (اختیاری)")
        self.code_field.setMaximumWidth(120)
        add_row.addWidget(self.code_field)
        self.name_field = QLineEdit()
        self.name_field.setPlaceholderText("نامِ بانک (مثلاً بانکِ ملی)")
        self.name_field.returnPressed.connect(self._save)
        add_row.addWidget(self.name_field, stretch=1)

        # طبقِ قانونِ ثابتِ چیدمانِ دکمه‌ها: دکمه‌ها باید کنارِ هم و به‌ترتیبِ
        # چپ‌به‌راست بمانند، بدونِ اینکه جهتِ فیلدهایِ کد/نامِ همین ردیف تغییر کند —
        # پس فقط خوشه‌یِ دکمه‌ها در یک زیرویجتِ LTR جداگانه قرار می‌گیرد.
        button_cluster = QWidget()
        button_cluster.setLayoutDirection(Qt.LeftToRight)
        button_cluster_layout = QHBoxLayout(button_cluster)
        button_cluster_layout.setContentsMargins(0, 0, 0, 0)
        button_cluster_layout.setSpacing(8)

        self.save_button = QPushButton("➕")
        self.save_button.setObjectName("primaryIconButton")
        self.save_button.setFixedWidth(48)
        self.save_button.setToolTip("افزودن")
        self.save_button.clicked.connect(self._save)
        button_cluster_layout.addWidget(self.save_button)
        self.cancel_button = QPushButton("↩️")
        self.cancel_button.setObjectName("iconButton")
        self.cancel_button.setFixedWidth(44)
        self.cancel_button.setToolTip("انصراف")
        self.cancel_button.clicked.connect(self._reset_form)
        self.cancel_button.setVisible(False)
        button_cluster_layout.addWidget(self.cancel_button)
        self.delete_button = QPushButton("🗑️")
        self.delete_button.setObjectName("dangerIconButton")
        self.delete_button.setFixedWidth(44)
        self.delete_button.setToolTip("حذف")
        self.delete_button.clicked.connect(self._delete)
        self.delete_button.setVisible(False)
        button_cluster_layout.addWidget(self.delete_button)

        add_row.addWidget(button_cluster)
        layout.addLayout(add_row)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["کد", "نامِ بانک"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table, stretch=1)

        outer.addWidget(wrap_scrollable(panel))

        self.set_field_help([
            (self.name_field, "نامِ بانک — بعداً در فرمِ ثبتِ چکِ دریافتی از این فهرست انتخاب می‌شود."),
            (self.table, "برایِ ویرایشِ یک بانک، رویِ ردیفش کلیک کنید."),
        ])

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        self.company_id = self._company_id()
        self._reset_form()
        if self.company_id is None:
            self.table.setRowCount(0)
            return
        rows = treasury_service.list_banks(self.company_id)
        self.table.setRowCount(len(rows))
        for row_index, r in enumerate(rows):
            code_item = QTableWidgetItem(r.code or "")
            code_item.setData(Qt.UserRole, r.bank_id)
            self.table.setItem(row_index, 0, code_item)
            self.table.setItem(row_index, 1, QTableWidgetItem(r.name))

    def _reset_form(self) -> None:
        self._editing_bank_id = None
        self.status_label.setText("")
        self.code_field.clear()
        self.name_field.clear()
        self.save_button.setToolTip("افزودن")
        self.cancel_button.setVisible(False)
        self.delete_button.setVisible(False)
        self.table.clearSelection()

    def _on_row_clicked(self, row: int, _column: int) -> None:
        code_item = self.table.item(row, 0)
        if code_item is None:
            return
        self._editing_bank_id = code_item.data(Qt.UserRole)
        self.status_label.setText("")
        self.code_field.setText(code_item.text())
        self.name_field.setText(self.table.item(row, 1).text())
        self.save_button.setToolTip("ذخیره‌یِ ویرایش")
        self.cancel_button.setVisible(True)
        self.delete_button.setVisible(True)

    def _save(self) -> None:
        if self.company_id is None:
            self.status_label.setText("ابتدا یک شرکت را انتخاب کنید.")
            return
        try:
            if self._editing_bank_id is not None:
                treasury_service.update_bank(self._editing_bank_id, self.company_id, self.name_field.text(), self.code_field.text())
            else:
                treasury_service.create_bank(self.company_id, self.name_field.text(), self.code_field.text())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()

    def _delete(self) -> None:
        if self.company_id is None or self._editing_bank_id is None:
            return
        confirm = QMessageBox.question(self, "حذفِ بانک", "این بانک حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            treasury_service.delete_bank(self._editing_bank_id, self.company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
