"""اجرایِ یک الگویِ گزارشِ سفارشی (طراحِ گزارش، فازِ ۲) — الگوها در
«طراحیِ الگویِ گزارش» (statement_template_designer.py) ساخته می‌شوند؛
این صفحه فقط یک الگو را انتخاب و برایِ بازه‌یِ تاریخِ دلخواه اجرا می‌کند."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtWidgets import QComboBox, QLabel

from peecha import numerals, session
from peecha.services import currencies as currencies_service
from peecha.services import reports as reports_service
from peecha.services import statement_templates as statement_templates_service
from peecha.ui.screens.reports_common import ReportScreenBase


class CustomStatementScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("گزارشِ سفارشی (طبقِ الگو)")

        self.extra_filter_row.addWidget(QLabel("الگو:"))
        self.template_combo = QComboBox()
        self.extra_filter_row.addWidget(self.template_combo)

        self.add_field_help([
            (
                self.template_combo,
                "الگویِ گزارشی که می‌خواهید اجرا کنید. الگوها در «طراحیِ الگویِ گزارش» ساخته می‌شوند؛ این صفحه فقط آن‌ها را برایِ بازه‌یِ تاریخِ دلخواه اجرا می‌کند.",
            ),
        ])

        self._currency_decimal_places = 0

    def refresh(self) -> None:
        company = session.current_company
        currency = None
        if company is not None:
            currency = next(
                (c for c in currencies_service.list_all_currencies() if c.currency_id == company.base_currency_id),
                None,
            )
        self._currency_decimal_places = currency.decimal_places if currency else 0

        self.template_combo.clear()
        if company is not None:
            for t in statement_templates_service.list_templates(company.company_id):
                self.template_combo.addItem(t.name, t.template_id)
        super().refresh()

    def _fmt(self, value: decimal.Decimal) -> str:
        return numerals.format_money(value, self._currency_decimal_places, None)

    def load_report(self, company_id: int, date_from: datetime.date, date_to: datetime.date):
        template_id = self.template_combo.currentData()
        headers = ["ردیف", "مبلغ"]
        if template_id is None:
            return headers, [], None

        try:
            lines = reports_service.compute_custom_statement(
                template_id, company_id, date_from, date_to, status_filter=self.status_filter()
            )
        except ValueError as exc:
            return headers, [["خطا", str(exc)]], None

        rows: list[list] = []
        self._all_row_bold = []
        for line in lines:
            indent = "    " * line.indent_level
            amount_text = self._fmt(line.amount) if line.amount is not None else ""
            rows.append([f"{indent}{line.label}", amount_text])
            self._all_row_bold.append(line.is_bold)

        return headers, rows, None
