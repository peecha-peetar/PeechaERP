"""مدیریتِ اقساط -- طبقِ درخواستِ صریح («روشِ دریافت/پرداختِ اقساطی»):
فهرستِ همه‌یِ اقساطِ برنامه‌ریزی‌شده (از طریقِ روشِ «اقساط» در فرمِ
دریافت/پرداخت) با وضعیتِ هرکدام. خودِ دریافت/پرداختِ یک قسط از همان فرمِ
عمومیِ دریافت/پرداخت (treasury_voucher.py، دکمه‌یِ 🔗) انجام می‌شود --
این صفحه فقط برایِ دیدِ کلی است."""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session as app_session
from peecha.services import commercial_documents as documents_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import installments as installments_service
from peecha.ui import theme
from peecha.ui.screens.commercial_document import DOC_TYPE_TITLES

_STATUS_LABELS = {"PENDING": "درانتظار", "OVERDUE": "معوقه", "PAID": "دریافت/پرداخت‌شده"}
_COLUMNS = ["نوع", "شماره‌یِ فاکتور", "طرفِ‌حساب", "قسط", "سررسید", "مبلغ", "وضعیت"]


class InstallmentsListScreen(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__()
        self._main_window = main_window
        self._parties_by_id: dict[int, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)

        title = QLabel("مدیریتِ اقساط")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("دریافت/پرداختِ هر قسط از فرمِ دریافت/پرداخت (دکمه‌یِ 🔗) انجام می‌شود."))

        filters = QHBoxLayout()
        filters.addWidget(QLabel("وضعیت"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("(همه)", None)
        for code, label in _STATUS_LABELS.items():
            self.status_filter.addItem(label, code)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.status_filter)
        filters.addStretch(1)
        layout.addLayout(filters)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

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

        status_code = self.status_filter.currentData()
        rows = installments_service.list_installments(
            company_id, status_codes=[status_code] if status_code else None,
        )
        self.table.setRowCount(len(rows))
        today = datetime.date.today()
        for row_index, line in enumerate(rows):
            try:
                doc, _lines = documents_service.get_document(line.document_id, company_id)
            except ValueError:
                doc = None
            overdue = line.status_code == "OVERDUE" or (line.status_code == "PENDING" and line.due_date < today)
            values = [
                DOC_TYPE_TITLES.get(doc.document_type_code, doc.document_type_code) if doc else "—",
                numerals.to_persian_digits(str(doc.document_no)) if doc else "—",
                self._parties_by_id.get(doc.counterparty_detail_account_id, "—") if doc else "—",
                numerals.to_persian_digits(str(line.installment_no)),
                numerals.format_jalali_date(line.due_date),
                numerals.format_company_amount(line.amount),
                _STATUS_LABELS.get(line.status_code, line.status_code),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if overdue and col_index in (4, 6):
                    item.setForeground(QColor(theme.DANGER))
                self.table.setItem(row_index, col_index, item)
        self.table.resizeRowsToContents()
