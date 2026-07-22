"""فهرستِ اسنادِ حسابداری — معادلِ Qt برایِ journal_entries_list.py/.kv در Kivy."""

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
from peecha.services import journal_entries as je_service

_STATUS_LABELS = {
    "DRAFT": "پیش‌نویس",
    "TEMPORARY": "موقت",
    "PERMANENT": "دائم",
    "REVERSED": "برگشت‌خورده",
    "CANCELLED": "ابطال‌شده",
}

_COLUMNS = ["وضعیت", "مبلغِ کل", "شرح", "تاریخ", "شماره"]


class JournalEntriesListScreen(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__()
        self._main_window = main_window
        self._entries: list[je_service.JournalEntrySummary] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("اسنادِ حسابداری")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        new_button = QPushButton("+ سندِ جدید")
        new_button.setObjectName("primaryButton")
        new_button.clicked.connect(self._open_new_entry)
        header.addWidget(new_button)
        layout.addLayout(header)

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("جستجو در شماره‌ی سند، شرح یا شماره‌ی عطف")
        self.search_field.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search_field)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self.table, stretch=1)

        delete_button = QPushButton("حذفِ سندِ انتخاب‌شده (موقت/پیش‌نویس)")
        delete_button.setObjectName("dangerButton")
        delete_button.clicked.connect(self._delete_selected)
        layout.addWidget(delete_button)

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        self._entries = je_service.list_journal_entries(company_id) if company_id is not None else []
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self.search_field.text().strip()
        filtered = [
            e for e in self._entries
            if not query
            or query in str(e.temporary_no)
            or query in (e.description or "")
            or query in (e.alternative_number or "")
        ]
        self.table.setRowCount(len(filtered))
        for row_index, e in enumerate(filtered):
            values = [
                _STATUS_LABELS.get(e.status_code, e.status_code),
                str(e.total_amount),
                e.description or "—",
                e.document_date.isoformat(),
                str(e.temporary_no),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, e.journal_entry_id)
                self.table.setItem(row_index, col_index, item)

    def _open_new_entry(self) -> None:
        self._main_window.open_screen("GL_JE", then=lambda screen: screen._reset_form())

    def _on_row_double_clicked(self, row: int, _column: int) -> None:
        journal_entry_id = self.table.item(row, 0).data(Qt.UserRole)
        self._main_window.open_screen("GL_JE", then=lambda screen: screen.edit_journal_entry(journal_entry_id))

    def _delete_selected(self) -> None:
        selected = self.table.selectedItems()
        if not selected:
            return
        journal_entry_id = selected[0].data(Qt.UserRole)
        company_id = self._company_id()
        if company_id is None:
            return
        confirm = QMessageBox.question(
            self, "حذفِ سند", "این سند حذف شود؟ این کار قابلِ بازگشت نیست.", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            je_service.delete_journal_entry(journal_entry_id, company_id, session.current_user.user_id if session.current_user else None)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()
