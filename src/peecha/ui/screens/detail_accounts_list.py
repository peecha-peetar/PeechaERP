"""فهرستِ واحدِ همه‌ی تفصیلی‌ها — معادلِ Qt برایِ detail_accounts_list.py/.kv
در Kivy. کلیک روی هر ردیف بسته به نوعِ گروهش، صفحه‌ی درست را باز می‌کند."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import detail_dimensions as dimensions_service

_GROUP_SCREEN_BY_PERSON_CODE = {
    "CUSTOMER": "customers",
    "SUPPLIER": "suppliers",
    "PERSONNEL": "personnel",
}

# طبقِ درخواستِ صریح: ۷ نوعِ «فرمِ خاص» صفحه‌ی اختصاصیِ خودشان را دارند —
# کلیک روی ردیفِ آن‌ها در فهرستِ واحد باید به همان صفحه برود، نه صفحه‌ی
# عمومیِ گروه‌هایِ «ساده» (GL_DIM).
_NAV_CODE_BY_DIMENSION_CODE = {
    "INVENTORY_ITEM": "GL_INVENTORY_ITEMS",
    "FIXED_ASSET": "GL_FIXED_ASSETS",
    "BANK_ACCOUNT": "GL_BANK_ACCOUNTS",
    "CASH_BOX": "GL_CASH_BOXES",
    "PETTY_CASH": "GL_PETTY_CASHES",
    "COST_CENTER": "GL_COST_CENTERS",
    "PROJECT": "GL_PROJECTS",
}

_COLUMNS = ["وضعیت", "نام", "کد", "سطح", "نوعِ تفصیلی"]


class DetailAccountsListScreen(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__()
        self._main_window = main_window
        self._entries: list[dimensions_service.UnifiedDetailAccountRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("تفصیلی‌ها")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        hint = QLabel(
            "همه‌ی مشتریان/تامین‌کنندگان/پرسنل/مراکزِ هزینه/پروژه‌ها و گروه‌های دیگرِ تفصیلی، یک‌جا — "
            "کلیک روی هر ردیف فرمِ مربوطه را باز می‌کند."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("جستجو در نوعِ تفصیلی، کد یا نام")
        self.search_field.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search_field)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._on_row_clicked)
        layout.addWidget(self.table, stretch=1)

    def refresh(self) -> None:
        company_id = session.current_company.company_id if session.current_company else None
        self._entries = dimensions_service.list_all_detail_accounts(company_id) if company_id is not None else []
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self.search_field.text().strip()
        filtered = [
            e for e in self._entries
            if not query or query in e.group_name or query in e.full_code or (e.name and query in e.name)
        ]
        self.table.setRowCount(len(filtered))
        for row_index, e in enumerate(filtered):
            values = [
                "فعال" if e.is_active else "غیرفعال",
                e.name or "—",
                e.full_code,
                str(e.level_no),
                e.group_name,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, (e.dimension_type_id, e.detail_account_id, e.person_group_code, e.group_name))
                self.table.setItem(row_index, col_index, item)

    def _on_row_clicked(self, row: int, _column: int) -> None:
        dimension_type_id, detail_account_id, person_group_code, group_name = self.table.item(row, 0).data(Qt.UserRole)
        self.open_entry(dimension_type_id, detail_account_id, person_group_code, group_name)

    def open_entry(
        self, dimension_type_id: int, detail_account_id: int, person_group_code: str | None, group_name: str = ""
    ) -> None:
        target_code = _GROUP_SCREEN_BY_PERSON_CODE.get(person_group_code or "")
        if target_code is not None:
            nav_code = {"customers": "GL_CUSTOMERS", "suppliers": "GL_SUPPLIERS", "personnel": "GL_PERSONNEL"}[target_code]
            self._main_window.open_screen(nav_code, then=lambda screen: screen.edit_person(detail_account_id))
            return

        specialized_nav_code = _NAV_CODE_BY_DIMENSION_CODE.get(group_name)
        if specialized_nav_code is not None:
            self._main_window.open_screen(
                specialized_nav_code, then=lambda screen: screen.edit_detail_account(detail_account_id)
            )
            return

        self._main_window.open_screen(
            "GL_DIM", then=lambda screen: screen.select_type_and_edit(dimension_type_id, detail_account_id)
        )
