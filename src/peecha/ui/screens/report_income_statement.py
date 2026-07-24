"""صورتِ سود و زیان — حساب‌هایِ درآمد/هزینه در سطحِ کل، با مقایسه‌یِ همان
بازه در یک سالِ پیش."""

from __future__ import annotations

import datetime
import decimal

from peecha import numerals, session
from peecha.services import currencies as currencies_service
from peecha.services import reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase

_CATEGORY_LABELS = {"REVENUE": "درآمدها", "EXPENSE": "هزینه‌ها"}


class IncomeStatementScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("صورتِ سود و زیان")
        self._currency_decimal_places = 0
        self._currency_symbol: str | None = None

    def refresh(self) -> None:
        company = session.current_company
        currency = None
        if company is not None:
            currency = next(
                (c for c in currencies_service.list_all_currencies() if c.currency_id == company.base_currency_id),
                None,
            )
        self._currency_decimal_places = currency.decimal_places if currency else 0
        self._currency_symbol = currency.symbol if currency else None
        super().refresh()

    def _fmt(self, value: decimal.Decimal) -> str:
        return numerals.format_money(value, self._currency_decimal_places, self._currency_symbol)

    def load_report(self, company_id: int, date_from: datetime.date, date_to: datetime.date):
        result = reports_service.compute_income_statement(company_id, date_from, date_to)

        headers = ["کد", "نام", "دسته", "دوره‌یِ جاری", "دوره‌یِ مشابهِ سالِ قبل"]
        rows: list[list] = []
        for r in result.rows:
            rows.append(
                [
                    r.full_code,
                    r.name,
                    _CATEGORY_LABELS.get(r.category_code, r.category_code),
                    self._fmt(r.current_amount),
                    self._fmt(r.previous_amount),
                ]
            )
        rows.append(["", "جمعِ درآمدها", "", self._fmt(result.total_revenue), ""])
        rows.append(["", "جمعِ هزینه‌ها", "", self._fmt(result.total_expense), ""])
        footer = ["", "سودِ (زیانِ) خالص", "", self._fmt(result.net_income), ""]
        return headers, rows, footer
