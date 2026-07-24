"""صورتِ تغییرات در حقوقِ صاحبانِ سهام — مانده‌یِ اول + افزایش/کاهشِ دوره +
مانده‌یِ آخر، به‌ازایِ هر حسابِ EQUITY (سطحِ کل)."""

from __future__ import annotations

import datetime
import decimal

from peecha import numerals, session
from peecha.services import currencies as currencies_service
from peecha.services import reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase, code_in_range


class EquityChangesScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("صورتِ تغییرات در حقوقِ صاحبانِ سهام")
        self.enable_code_range_filter()
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
        super().refresh()

    def _fmt(self, value: decimal.Decimal) -> str:
        return numerals.format_money(value, self._currency_decimal_places, None)

    def load_report(self, company_id: int, date_from: datetime.date, date_to: datetime.date):
        code_from, code_to = self.code_range()
        rows_data = reports_service.compute_equity_changes(company_id, date_from, date_to, status_filter=self.status_filter())
        rows_data = [r for r in rows_data if code_in_range(r.full_code, code_from, code_to)]

        headers = ["کد", "نام", "مانده‌ی اول", "افزایش", "کاهش", "مانده‌ی آخر"]
        rows: list[list] = []
        total_opening = decimal.Decimal(0)
        total_increase = decimal.Decimal(0)
        total_decrease = decimal.Decimal(0)
        total_closing = decimal.Decimal(0)
        for r in rows_data:
            total_opening += r.opening_balance
            total_increase += r.increases
            total_decrease += r.decreases
            total_closing += r.closing_balance
            rows.append(
                [
                    r.full_code,
                    r.name,
                    self._fmt(r.opening_balance),
                    self._fmt(r.increases),
                    self._fmt(r.decreases),
                    self._fmt(r.closing_balance),
                ]
            )
        footer = [
            "",
            "جمعِ کل",
            self._fmt(total_opening),
            self._fmt(total_increase),
            self._fmt(total_decrease),
            self._fmt(total_closing),
        ]
        return headers, rows, footer
