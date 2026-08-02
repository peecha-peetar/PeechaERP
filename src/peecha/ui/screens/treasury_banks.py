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
from peecha.ui.widgets import FieldHelpMixin


class TreasuryBanksScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.company_id: int | None = None

        layout = QVBoxLayout(self)
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
        self.name_field.returnPressed.connect(self._add)
        add_row.addWidget(self.name_field, stretch=1)
        add_button = QPushButton("+ افزودن")
        add_button.setObjectName("primaryButton")
        add_button.clicked.connect(self._add)
        add_row.addWidget(add_button)
        layout.addLayout(add_row)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["کد", "نامِ بانک"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self._delete)
        layout.addWidget(self.table, stretch=1)

        self.set_field_help([
            (self.name_field, "نامِ بانک — بعداً در فرمِ ثبتِ چکِ دریافتی از این فهرست انتخاب می‌شود."),
            (self.table, "برایِ حذفِ یک بانک، رویِ ردیفش دابل‌کلیک کنید."),
        ])

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        self.company_id = self._company_id()
        self.status_label.setText("")
        self.code_field.clear()
        self.name_field.clear()
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

    def _add(self) -> None:
        if self.company_id is None:
            self.status_label.setText("ابتدا یک شرکت را انتخاب کنید.")
            return
        try:
            treasury_service.create_bank(self.company_id, self.name_field.text(), self.code_field.text())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()

    def _delete(self, row: int, _column: int) -> None:
        if self.company_id is None:
            return
        bank_id = self.table.item(row, 0).data(Qt.UserRole)
        confirm = QMessageBox.question(self, "حذفِ بانک", "این بانک حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            treasury_service.delete_bank(bank_id, self.company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
