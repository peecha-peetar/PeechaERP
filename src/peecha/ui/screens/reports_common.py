"""پایه‌یِ مشترکِ صفحاتِ گزارش — نوارِ فیلترِ بازه‌یِ تاریخ + نوارِ خروجی
(چاپ/PDF/Excel) + جدولِ نتایج. پیرو الگویِ کشف‌شده در journal_entries_list.py:
بدونِ QScrollArea اضافه (خودِ QTableWidget اسکرول می‌کند)، هدر/نوارها ثابت در
VBoxِ بیرونی."""

from __future__ import annotations

import datetime

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.ui import report_export
from peecha.ui.widgets import JalaliDateEdit


class ReportScreenBase(QWidget):
    """زیرکلاس‌ها باید `load_report(company_id, date_from, date_to)` را
    override کنند و (headers, rows, footer) برگردانند؛ فیلترهایِ اختصاصیِ
    خودشان را می‌توانند به `self.extra_filter_row` اضافه کنند."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title
        self._headers: list[str] = []
        self._rows: list[list] = []
        self._footer: list | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        header.addWidget(title_label)
        header.addStretch(1)
        layout.addLayout(header)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("از تاریخ:"))
        self.date_from = JalaliDateEdit()
        filter_row.addWidget(self.date_from)
        filter_row.addWidget(QLabel("تا تاریخ:"))
        self.date_to = JalaliDateEdit()
        filter_row.addWidget(self.date_to)

        self.extra_filter_row = QHBoxLayout()
        filter_row.addLayout(self.extra_filter_row)

        apply_button = QPushButton("اعمالِ فیلتر")
        apply_button.setObjectName("primaryButton")
        apply_button.clicked.connect(self._reload)
        filter_row.addWidget(apply_button)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        export_row = QHBoxLayout()
        print_button = QPushButton("🖨 چاپ")
        print_button.setObjectName("flatButton")
        print_button.clicked.connect(self._on_print)
        export_row.addWidget(print_button)

        pdf_button = QPushButton("📄 خروجیِ PDF")
        pdf_button.setObjectName("flatButton")
        pdf_button.clicked.connect(self._on_export_pdf)
        export_row.addWidget(pdf_button)

        excel_button = QPushButton("📊 خروجیِ Excel")
        excel_button.setObjectName("flatButton")
        excel_button.clicked.connect(self._on_export_excel)
        export_row.addWidget(excel_button)
        export_row.addStretch(1)
        layout.addLayout(export_row)

        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        layout.addWidget(self.table, stretch=1)

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def _default_date_range(self) -> tuple[datetime.date, datetime.date]:
        today = datetime.date.today()
        fiscal_year = session.current_fiscal_year
        start = fiscal_year.start_date if fiscal_year is not None else today.replace(month=1, day=1)
        return start, today

    def refresh(self) -> None:
        start, end = self._default_date_range()
        self.date_from.setDate(start)
        self.date_to.setDate(end)
        self._reload()

    def _reload(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            self._headers, self._rows, self._footer = [], [], None
            self._set_table([], [], None)
            return
        headers, rows, footer = self.load_report(company_id, self.date_from.date(), self.date_to.date())
        self._headers, self._rows, self._footer = headers, rows, footer
        self._set_table(headers, rows, footer)

    def _set_table(self, headers: list[str], rows: list[list], footer: list | None) -> None:
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        extra = 1 if footer else 0
        self.table.setRowCount(len(rows) + extra)
        for row_index, row in enumerate(rows):
            for col_index, value in enumerate(row):
                self.table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
        if footer:
            footer_row = len(rows)
            for col_index, value in enumerate(footer):
                item = QTableWidgetItem(str(value))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                self.table.setItem(footer_row, col_index, item)

    def load_report(
        self, company_id: int, date_from: datetime.date, date_to: datetime.date
    ) -> tuple[list[str], list[list], list | None]:
        raise NotImplementedError

    def _on_print(self) -> None:
        report_export.print_report(self, self._title, self._headers, self._rows, self._footer)

    def _on_export_pdf(self) -> None:
        report_export.export_report_pdf(self, self._title, self._headers, self._rows, self._footer)

    def _on_export_excel(self) -> None:
        report_export.export_report_excel(self, self._title, self._headers, self._rows, self._footer)
