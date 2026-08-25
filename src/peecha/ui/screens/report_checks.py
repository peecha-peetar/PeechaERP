"""گزارشِ چک‌ها — طبقِ درخواستِ صریح: فهرستِ ترکیبیِ همه‌یِ چک‌هایِ دریافتی و
پرداختی (نه فقط درجریانِ وصول، بلکه با هر وضعیتی — «فیلترِ تمامِ ورودی‌ها»)،
با فیلترِ نوعِ چک (دریافتی/پرداختی)، بازه‌یِ سررسید، بازه‌یِ تاریخِ
دریافت/صدور، طرفِ‌حساب، وضعیتِ چک، و نامِ بانک؛ در پایان، چاپ/PDF/Excel.

طبقِ گزارشِ صریح («گزارشِ چک‌هایِ درجریانِ وصول» در treasury_reports.py):
آن گزارش عمداً محدود به چک‌هایِ هنوز وصول‌نشده و نزدیکِ سررسید است — این
یکی مکملِ آن است: بایگانیِ کاملِ همه‌یِ چک‌ها با هر وضعیتی، برایِ مرور/چاپِ
گزارشِ عمومی."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.services import treasury as treasury_service
from peecha.ui import report_export
from peecha.ui.widgets import FieldHelpMixin, JalaliDateEdit, wrap_scrollable_with_footer

_STATUS_LABELS = {
    "IN_HAND": "نزدِ صندوق (دریافتی)",
    "DEPOSITED": "واگذارشده به بانک (دریافتی)",
    "CLEARED": "وصول‌شده",
    "BOUNCED": "برگشت‌خورده",
    "ENDORSED": "خرج‌شده نزدِ شخصِ ثالث (دریافتی)",
    "ISSUED": "صادر/نزدِ گیرنده (پرداختی)",
    "VOIDED": "ابطال‌شده (پرداختی)",
}
_STATUS_OPTIONS: list[tuple[str | None, str]] = [(None, "— همه —")] + list(_STATUS_LABELS.items())

_COLUMNS = ["نوع", "شماره‌یِ چک", "بانک", "طرفِ‌حساب", "مبلغ", "تاریخِ سررسید", "تاریخِ دریافت/صدور", "وضعیت"]
_REPORT_TITLE = "گزارشِ چک‌ها"


class ChecksReportScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[tuple] = []
        self._total = decimal.Decimal(0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(16)

        title = QLabel(_REPORT_TITLE)
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        kind_row = QHBoxLayout()
        kind_row.addWidget(QLabel("نوعِ چک:"))
        self.received_checkbox = QCheckBox("دریافتی")
        self.received_checkbox.setChecked(True)
        self.received_checkbox.stateChanged.connect(self.refresh)
        kind_row.addWidget(self.received_checkbox)
        self.issued_checkbox = QCheckBox("پرداختی")
        self.issued_checkbox.setChecked(True)
        self.issued_checkbox.stateChanged.connect(self.refresh)
        kind_row.addWidget(self.issued_checkbox)

        kind_row.addWidget(QLabel("وضعیت:"))
        self.status_combo = QComboBox()
        for code, label in _STATUS_OPTIONS:
            self.status_combo.addItem(label, code)
        self.status_combo.currentIndexChanged.connect(self.refresh)
        kind_row.addWidget(self.status_combo)
        kind_row.addStretch(1)
        layout.addLayout(kind_row)

        due_row = QHBoxLayout()
        self.due_filter_checkbox = QCheckBox("فیلترِ بازه‌یِ سررسید:")
        self.due_filter_checkbox.stateChanged.connect(self.refresh)
        due_row.addWidget(self.due_filter_checkbox)
        self.due_from_field = JalaliDateEdit()
        self.due_from_field.textChanged.connect(self.refresh)
        due_row.addWidget(self.due_from_field)
        due_row.addWidget(QLabel("تا"))
        self.due_to_field = JalaliDateEdit()
        self.due_to_field.textChanged.connect(self.refresh)
        due_row.addWidget(self.due_to_field)

        self.received_date_filter_checkbox = QCheckBox("فیلترِ بازه‌یِ تاریخِ دریافت/صدور:")
        self.received_date_filter_checkbox.stateChanged.connect(self.refresh)
        due_row.addWidget(self.received_date_filter_checkbox)
        self.received_from_field = JalaliDateEdit()
        self.received_from_field.textChanged.connect(self.refresh)
        due_row.addWidget(self.received_from_field)
        due_row.addWidget(QLabel("تا"))
        self.received_to_field = JalaliDateEdit()
        self.received_to_field.textChanged.connect(self.refresh)
        due_row.addWidget(self.received_to_field)
        due_row.addStretch(1)
        layout.addLayout(due_row)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("طرفِ‌حساب:"))
        self.counterparty_field = QLineEdit()
        self.counterparty_field.setPlaceholderText("جستجو در نامِ طرفِ‌حساب")
        self.counterparty_field.textChanged.connect(self.refresh)
        search_row.addWidget(self.counterparty_field, stretch=1)

        search_row.addWidget(QLabel("بانک:"))
        self.bank_field = QLineEdit()
        self.bank_field.setPlaceholderText("جستجو در نامِ بانک")
        self.bank_field.textChanged.connect(self.refresh)
        search_row.addWidget(self.bank_field, stretch=1)
        layout.addLayout(search_row)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("sectionHint")
        layout.addWidget(self.summary_label)

        print_button = QPushButton("🖨 چاپ")
        print_button.setObjectName("flatButton")
        print_button.clicked.connect(self._on_print)
        pdf_button = QPushButton("📄 خروجیِ PDF")
        pdf_button.setObjectName("flatButton")
        pdf_button.clicked.connect(self._on_export_pdf)
        excel_button = QPushButton("📊 خروجیِ Excel")
        excel_button.setObjectName("flatButton")
        excel_button.clicked.connect(self._on_export_excel)

        outer.addWidget(wrap_scrollable_with_footer(panel, [print_button, pdf_button, excel_button]))

        self.set_field_help([
            (self.received_checkbox, "چک‌هایِ دریافتی در گزارش بیایند یا نه."),
            (self.issued_checkbox, "چک‌هایِ پرداختی در گزارش بیایند یا نه."),
            (
                self.status_combo,
                "فقط چک‌هایی با این وضعیتِ مشخص نشان داده شوند؛ «— همه —» یعنی بدونِ این فیلتر — "
                "یعنی همه‌یِ وضعیت‌ها، نه فقط چک‌هایِ درجریانِ وصول.",
            ),
            (self.due_filter_checkbox, "فقط چک‌هایی که سررسیدشان در این بازه است."),
            (
                self.received_date_filter_checkbox,
                "فقط چک‌هایی که تاریخِ دریافت (برایِ چکِ دریافتی) یا تاریخِ صدور (برایِ چکِ پرداختی)شان در این بازه است.",
            ),
            (self.counterparty_field, "جستجویِ زنده در نامِ طرفِ‌حساب (پرداخت‌کننده‌یِ چکِ دریافتی یا گیرنده‌یِ چکِ پرداختی)."),
            (self.bank_field, "جستجویِ زنده در نامِ بانک."),
        ])

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        self._rows = []
        self._total = decimal.Decimal(0)
        self.table.setRowCount(0)
        self.summary_label.setText("")
        if company_id is None:
            return

        status_filter = self.status_combo.currentData()
        due_on = self.due_filter_checkbox.isChecked()
        due_from = self.due_from_field.date() if due_on else None
        due_to = self.due_to_field.date() if due_on else None
        recv_on = self.received_date_filter_checkbox.isChecked()
        recv_from = self.received_from_field.date() if recv_on else None
        recv_to = self.received_to_field.date() if recv_on else None
        counterparty_query = self.counterparty_field.text().strip()
        bank_query = self.bank_field.text().strip()

        rows: list[tuple] = []
        if self.received_checkbox.isChecked():
            for c in treasury_service.list_received_checks(company_id):
                if status_filter is not None and c.status_code != status_filter:
                    continue
                if due_from is not None and c.due_date < due_from:
                    continue
                if due_to is not None and c.due_date > due_to:
                    continue
                if recv_from is not None and c.received_date < recv_from:
                    continue
                if recv_to is not None and c.received_date > recv_to:
                    continue
                if counterparty_query and counterparty_query not in (c.drawer_name or ""):
                    continue
                if bank_query and bank_query not in (c.drawee_bank_name or ""):
                    continue
                rows.append((
                    "دریافتی", c.check_no, c.drawee_bank_name or "—", c.drawer_name or "—",
                    c.amount, c.due_date, c.received_date, _STATUS_LABELS.get(c.status_code, c.status_code),
                ))
        if self.issued_checkbox.isChecked():
            for c in treasury_service.list_issued_checks(company_id):
                if status_filter is not None and c.status_code != status_filter:
                    continue
                if due_from is not None and c.due_date < due_from:
                    continue
                if due_to is not None and c.due_date > due_to:
                    continue
                if recv_from is not None and c.issue_date < recv_from:
                    continue
                if recv_to is not None and c.issue_date > recv_to:
                    continue
                if counterparty_query and counterparty_query not in (c.payee_name or ""):
                    continue
                if bank_query and bank_query not in (c.bank_account_label or ""):
                    continue
                rows.append((
                    "پرداختی", c.check_no, c.bank_account_label or "—", c.payee_name or "—",
                    c.amount, c.due_date, c.issue_date, _STATUS_LABELS.get(c.status_code, c.status_code),
                ))

        rows.sort(key=lambda r: r[5])
        self._rows = rows
        self.table.setRowCount(len(rows))
        total = decimal.Decimal(0)
        for row_index, r in enumerate(rows):
            total += r[4]
            values = [
                r[0], r[1], r[2], r[3],
                numerals.format_money(r[4], 0, None),
                numerals.format_jalali_date(r[5]),
                numerals.format_jalali_date(r[6]),
                r[7],
            ]
            for col_index, value in enumerate(values):
                self.table.setItem(row_index, col_index, QTableWidgetItem(value))
        self._total = total
        self.summary_label.setText(
            f"{numerals.to_persian_digits(str(len(rows)))} چک — جمعِ مبلغ: {numerals.format_money(total, 0, None)}"
        )

    def _export_rows(self) -> tuple[list[str], list[list], list]:
        table_rows = [
            [
                r[0], r[1], r[2], r[3], numerals.format_money(r[4], 0, None),
                numerals.format_jalali_date(r[5]), numerals.format_jalali_date(r[6]), r[7],
            ]
            for r in self._rows
        ]
        footer = ["", "", "", "جمعِ کل", numerals.format_money(self._total, 0, None), "", "", ""]
        return list(_COLUMNS), table_rows, footer

    def _filters_summary(self) -> list[tuple[str, str]]:
        parts: list[tuple[str, str]] = []
        kinds = []
        if self.received_checkbox.isChecked():
            kinds.append("دریافتی")
        if self.issued_checkbox.isChecked():
            kinds.append("پرداختی")
        parts.append(("نوع", "، ".join(kinds) or "—"))
        if self.status_combo.currentData() is not None:
            parts.append(("وضعیت", self.status_combo.currentText()))
        if self.due_filter_checkbox.isChecked():
            parts.append((
                "بازه‌یِ سررسید",
                f"{numerals.format_jalali_date(self.due_from_field.date())} تا {numerals.format_jalali_date(self.due_to_field.date())}",
            ))
        if self.received_date_filter_checkbox.isChecked():
            parts.append((
                "بازه‌یِ تاریخِ دریافت/صدور",
                f"{numerals.format_jalali_date(self.received_from_field.date())} تا {numerals.format_jalali_date(self.received_to_field.date())}",
            ))
        if self.counterparty_field.text().strip():
            parts.append(("طرفِ‌حساب", self.counterparty_field.text().strip()))
        if self.bank_field.text().strip():
            parts.append(("بانک", self.bank_field.text().strip()))
        return parts

    def _export_kwargs(self) -> dict:
        return {
            "company_name": session.current_company.display_name if session.current_company else "",
            "report_date": numerals.format_jalali_date(datetime.date.today()),
            "filters": self._filters_summary(),
        }

    def _on_print(self) -> None:
        headers, rows, footer = self._export_rows()
        report_export.print_report(self, _REPORT_TITLE, headers, rows, footer, **self._export_kwargs())

    def _on_export_pdf(self) -> None:
        headers, rows, footer = self._export_rows()
        report_export.export_report_pdf(self, _REPORT_TITLE, headers, rows, footer, **self._export_kwargs())

    def _on_export_excel(self) -> None:
        headers, rows, footer = self._export_rows()
        report_export.export_report_excel(self, _REPORT_TITLE, headers, rows, footer, **self._export_kwargs())
