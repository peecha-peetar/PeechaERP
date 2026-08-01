"""گزارشِ خزانه‌داری: چک‌هایِ دریافتی/پرداختیِ درجریانِ وصول، مرتب‌شده بر
اساسِ نزدیکیِ سررسید (سررسیدگذشته‌ها هم مشخص می‌شوند) — طبقِ درخواستِ
صریحِ کاربر برایِ «گزارشاتِ خزانه‌داری»."""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.services import treasury as treasury_service
from peecha.ui import theme
from peecha.ui.widgets import FieldHelpMixin

_RECEIVED_PENDING = ["IN_HAND", "DEPOSITED"]
_ISSUED_PENDING = ["ISSUED"]
_RECEIVED_STATUS_LABELS = {"IN_HAND": "نزدِ صندوق", "DEPOSITED": "واگذارشده به بانک"}
_ISSUED_STATUS_LABELS = {"ISSUED": "صادر/نزدِ گیرنده"}


class TreasuryChecksDueScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("گزارشِ چک‌هایِ درجریانِ وصول")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("نمایشِ چک‌هایِ تا"))
        self.days_spin = QSpinBox()
        self.days_spin.setRange(1, 365)
        self.days_spin.setValue(14)
        self.days_spin.valueChanged.connect(self.refresh)
        filter_row.addWidget(self.days_spin)
        filter_row.addWidget(QLabel("روزِ آینده (چک‌هایِ سررسیدگذشته همیشه نشان داده می‌شوند)"))
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["نوع", "شماره‌یِ چک", "طرف", "مبلغ", "سررسید", "وضعیت", "روزِ باقی‌مانده"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

        self.set_field_help([
            (
                self.table,
                "چک‌هایِ دریافتی (نزدِ صندوق/واگذارشده به بانک) و چک‌هایِ پرداختی (صادر/نزدِ گیرنده) که هنوز وصول نشده‌اند، "
                "بر اساسِ نزدیکیِ سررسید مرتب شده‌اند؛ عددِ منفی یعنی سررسید گذشته است.",
            ),
        ])

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        self.table.setRowCount(0)
        if company_id is None:
            return

        within_days = self.days_spin.value()
        today = datetime.date.today()
        rows: list[tuple[str, str, str, object, datetime.date, str, int]] = []

        for c in treasury_service.list_received_checks(company_id, status_codes=_RECEIVED_PENDING):
            days_left = (c.due_date - today).days
            if days_left <= within_days:
                rows.append(("دریافتی", c.check_no, c.drawer_name or "—", c.amount, c.due_date, _RECEIVED_STATUS_LABELS.get(c.status_code, c.status_code), days_left))
        for c in treasury_service.list_issued_checks(company_id, status_codes=_ISSUED_PENDING):
            days_left = (c.due_date - today).days
            if days_left <= within_days:
                rows.append(("پرداختی", c.check_no, c.payee_name or "—", c.amount, c.due_date, _ISSUED_STATUS_LABELS.get(c.status_code, c.status_code), days_left))

        rows.sort(key=lambda r: r[4])
        self.table.setRowCount(len(rows))
        for row_index, (kind, check_no, party, amount, due_date, status_label, days_left) in enumerate(rows):
            values = [
                kind,
                check_no,
                party,
                numerals.format_money(amount, 0, None),
                numerals.format_jalali_date(due_date),
                status_label,
                numerals.to_persian_digits(str(days_left)),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if days_left < 0:
                    item.setForeground(QColor(theme.DANGER))
                self.table.setItem(row_index, col_index, item)
