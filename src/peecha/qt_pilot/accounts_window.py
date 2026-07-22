"""پنجره‌ی فهرستِ حساب‌ها — نمونه‌ی آزمایشیِ Qt6.

فقط برای سنجشِ جدولِ RTL/فارسیِ Qt در برابرِ RecycleView دستیِ Kivy —
بدونِ ادیت/حذف، فقط نمایشِ فهرست."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services.chart_of_accounts import list_accounts

_STYLE = """
QWidget#root {
    background-color: #F6F5FB;
}
QLabel#title {
    font-size: 22px;
    font-weight: bold;
    color: #14173A;
}
QLineEdit {
    background-color: #F4F3FA;
    border: 1px solid #E4E1F5;
    border-radius: 10px;
    padding: 8px 12px;
    font-size: 14px;
    color: #14173A;
}
QTableWidget {
    background-color: #FFFFFF;
    border: none;
    border-radius: 12px;
    gridline-color: #EDEBF7;
    font-size: 13px;
}
QHeaderView::section {
    background-color: #F4F3FA;
    color: #6B7280;
    padding: 8px;
    border: none;
    font-weight: bold;
}
"""

_COLUMNS = ["نوع", "دسته", "ماهیت", "قابل ثبت", "سطح", "نام", "کد کامل"]


class AccountsWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("پیچا — فهرستِ حساب‌ها (نمونه‌ی Qt6)")
        self.resize(1000, 640)

        root = QWidget()
        root.setObjectName("root")
        root.setStyleSheet(_STYLE)
        self.setCentralWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("کدینگِ حساب‌ها")
        title.setObjectName("title")
        layout.addWidget(title)

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("جستجو در کد یا نامِ حساب")
        self.search_field.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search_field)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setLayoutDirection(Qt.RightToLeft)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        layout.addWidget(self.table)

        self._rows = []
        self._load_accounts()

    def _load_accounts(self) -> None:
        company_id = session.current_company.company_id if session.current_company else None
        self._rows = list_accounts(company_id) if company_id is not None else []
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self.search_field.text().strip()
        filtered = [
            r for r in self._rows if not query or query in r.full_code or query in r.name
        ]
        self.table.setRowCount(len(filtered))
        for row_index, account in enumerate(filtered):
            values = [
                account.account_type_code,
                account.category_code,
                account.nature_code,
                "بله" if account.is_postable else "خیر",
                str(account.account_level),
                account.name,
                account.full_code,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row_index, col_index, item)
