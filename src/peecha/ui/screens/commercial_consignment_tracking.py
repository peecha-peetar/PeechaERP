"""پیگیریِ فاکتورهایِ امانی -- طبقِ درخواستِ صریح (سیستمِ امانیِ خروجی/
ورودی، هردو جهت). تسویه (تبدیل به فاکتورِ واقعیِ فروش/خرید) از طریقِ همان
دکمه‌یِ «تبدیل به فاکتور» در خودِ فرمِ سند (commercial_document.py) انجام
می‌شود -- این صفحه فقط دیدِ کلیِ مانده و بازگردانیِ کالایِ فروخته‌نشده/
مصرف‌نشده را اضافه می‌کند (services/commercial_consignment.py)."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session as app_session
from peecha.services import commercial_consignment as consignment_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.ui.screens.commercial_document import DOC_TYPE_TITLES
from peecha.ui.screens.journal_entry import _AmountField
from peecha.ui.widgets import JalaliDateEdit

_DOCUMENT_COLUMNS = ["نوع", "شماره", "طرفِ‌حساب", "تاریخ"]
_LINE_COLUMNS = ["کالا", "مقدار", "تسویه‌شده", "بازگشتی", "مانده", "مقدارِ بازگشت"]


class ConsignmentTrackingScreen(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__()
        self._main_window = main_window
        self._parties_by_id: dict[int, str] = {}
        self._documents: list = []
        self._selected_document = None
        self._qty_fields: dict[int, _AmountField] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)

        title = QLabel("پیگیریِ فاکتورهایِ امانی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel(
            "فقط اسنادِ امانیِ ثبتِ‌نهایی‌شده‌ای که هنوز به‌طورِ کامل تسویه/بازگشت نشده‌اند نمایش داده می‌شوند. "
            "تسویه (تبدیل به فاکتورِ واقعیِ فروش/خرید) از طریقِ دکمه‌یِ «تبدیل به فاکتور» در خودِ فرمِ سند انجام می‌شود؛ "
            "این‌جا فقط بازگردانیِ کالایِ فروخته‌نشده/مصرف‌نشده ثبت می‌شود."
        ))

        self.document_table = QTableWidget(0, len(_DOCUMENT_COLUMNS))
        self.document_table.setHorizontalHeaderLabels(_DOCUMENT_COLUMNS)
        self.document_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.document_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.document_table.verticalHeader().setVisible(False)
        self.document_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.document_table.itemSelectionChanged.connect(self._on_document_selected)
        layout.addWidget(self.document_table, stretch=1)

        layout.addWidget(QLabel("ردیف‌هایِ سندِ انتخاب‌شده"))
        self.line_table = QTableWidget(0, len(_LINE_COLUMNS))
        self.line_table.setHorizontalHeaderLabels(_LINE_COLUMNS)
        self.line_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.line_table.verticalHeader().setVisible(False)
        self.line_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.line_table, stretch=2)

        action_row = QHBoxLayout()
        action_row.addWidget(QLabel("تاریخِ بازگشت"))
        self.return_date_field = JalaliDateEdit()
        action_row.addWidget(self.return_date_field)
        return_button = QPushButton("↩️ ثبتِ بازگشت")
        return_button.setObjectName("primaryButton")
        return_button.clicked.connect(self._submit_return)
        action_row.addWidget(return_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._parties_by_id = {}
        for c in dimensions_service.list_customers(company_id):
            self._parties_by_id[c["detail_account_id"]] = f"{c['code']} — {c['name'] or ''}"
        for s in dimensions_service.list_suppliers(company_id):
            self._parties_by_id[s["detail_account_id"]] = f"{s['code']} — {s['name'] or ''}"

        self._documents = consignment_service.list_open_consignments(company_id)
        self.document_table.setRowCount(len(self._documents))
        for row_index, doc in enumerate(self._documents):
            values = [
                DOC_TYPE_TITLES.get(doc.document_type_code, doc.document_type_code),
                numerals.to_persian_digits(str(doc.document_no)),
                self._parties_by_id.get(doc.counterparty_detail_account_id, "—"),
                numerals.format_jalali_date(doc.document_date),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, doc.document_id)
                self.document_table.setItem(row_index, col_index, item)
        self.document_table.resizeRowsToContents()
        self.status_label.setText("")
        self._refresh_lines_table()

    def _on_document_selected(self) -> None:
        rows = self.document_table.selectionModel().selectedRows()
        if not rows:
            self._selected_document = None
        else:
            item = self.document_table.item(rows[0].row(), 0)
            document_id = item.data(Qt.UserRole)
            self._selected_document = next((d for d in self._documents if d.document_id == document_id), None)
        self._refresh_lines_table()

    def _refresh_lines_table(self) -> None:
        self.line_table.setRowCount(0)
        self._qty_fields = {}
        company_id = self._company_id()
        if company_id is None or self._selected_document is None:
            return
        items_by_id = {it.item_id: it for it in catalog_service.list_items(company_id)}
        statuses = consignment_service.get_consignment_status(self._selected_document.document_id, company_id)
        open_statuses = [s for s in statuses if s.remaining_quantity > 0]
        self.line_table.setRowCount(len(open_statuses))
        for row_index, status in enumerate(open_statuses):
            item = items_by_id.get(status.item_id)
            values = [
                f"{item.code} — {item.name or ''}" if item else str(status.item_id),
                numerals.format_money(status.quantity, 3),
                numerals.format_money(status.settled_quantity, 3),
                numerals.format_money(status.returned_quantity, 3),
                numerals.format_money(status.remaining_quantity, 3),
            ]
            for col_index, value in enumerate(values):
                self.line_table.setItem(row_index, col_index, QTableWidgetItem(value))
            qty_field = _AmountField()
            qty_field.setDecimals(3)
            qty_field.setValue(0)
            self._qty_fields[status.line_id] = qty_field
            self.line_table.setCellWidget(row_index, len(_LINE_COLUMNS) - 1, qty_field)
        self.line_table.resizeRowsToContents()

    def _submit_return(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_document is None:
            self.status_label.setObjectName("statusError")
            self.status_label.setText("ابتدا یک سندِ امانی را از فهرستِ بالا انتخاب کنید.")
            return
        quantities = {
            line_id: decimal.Decimal(str(field.value())) for line_id, field in self._qty_fields.items() if field.value() > 0
        }
        if not quantities:
            self.status_label.setObjectName("statusError")
            self.status_label.setText("حداقل برایِ یک ردیف مقدارِ بازگشت وارد کنید.")
            return
        try:
            if self._selected_document.document_type_code == "CONSIGNMENT_OUT":
                consignment_service.return_unsold_consignment_out(
                    self._selected_document.document_id, company_id, app_session.current_user.user_id,
                    quantities, self.return_date_field.date(),
                )
            else:
                consignment_service.return_unused_consignment_in(
                    self._selected_document.document_id, company_id, app_session.current_user.user_id,
                    quantities, self.return_date_field.date(),
                )
        except ValueError as exc:
            self.status_label.setObjectName("statusError")
            self.status_label.setText(str(exc))
            return
        # طبقِ رفعِ باگِ واقعی: refresh() خودش status_label را برایِ
        # نمایشِ خطاهایِ فهرست خالی می‌کند -- اگر پیامِ موفقیت قبل از
        # آن گذاشته شود، بلافاصله در سکوت پاک می‌شود.
        self.refresh()
        self.status_label.setObjectName("statusSuccess")
        self.status_label.setText("بازگشت ثبت شد.")
