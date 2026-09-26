"""صورتِ سود و زیان — حساب‌هایِ درآمد/هزینه در سطحِ کل، با مقایسه‌یِ همان
بازه در یک سالِ پیش."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtWidgets import QMessageBox

from peecha import numerals, session
from peecha.services import currencies as currencies_service
from peecha.services import reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase, code_in_range

_CATEGORY_LABELS = {"REVENUE": "درآمدها", "COGS": "بهایِ تمام‌شده", "EXPENSE": "هزینه‌ها"}


class IncomeStatementScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("صورتِ سود و زیان")
        self.enable_code_range_filter()
        self.enable_cost_center_filter()
        self.enable_jasper_report("INCOME_STATEMENT")
        self._currency_decimal_places = 0

    def code_range_account_level(self) -> int | None:
        # ردیف‌هایِ سود و زیان همیشه حساب‌هایِ سطحِ گروه (رول‌آپ‌شده) هستند.
        return 1

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
        result = reports_service.compute_income_statement(
            company_id,
            date_from,
            date_to,
            status_filter=self.status_filter(),
            cost_center_id=self.cost_center_id(),
        )

        headers = ["کد", "نام", "دسته", "دوره‌یِ جاری", "دوره‌یِ مشابهِ سالِ قبل"]
        rows: list[list] = []
        for r in result.rows:
            if not code_in_range(r.full_code, code_from, code_to):
                continue
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
        rows.append(["", "جمعِ بهایِ تمام‌شده", "", self._fmt(result.total_cogs), ""])
        rows.append(["", "سودِ (زیانِ) ناخالص", "", self._fmt(result.gross_profit), ""])
        rows.append(["", "جمعِ هزینه‌ها", "", self._fmt(result.total_expense), ""])
        footer = ["", "سودِ (زیانِ) خالص", "", self._fmt(result.net_income), ""]
        return headers, rows, footer

    def _build_jasper_rows_and_params(self) -> tuple[list[dict], dict] | None:
        if not self._rows:
            QMessageBox.information(self, "گزارش", "داده‌ای برایِ چاپ وجود ندارد.")
            return None

        field_names = ["account_code", "account_name", "category_label", "current_amount_display", "previous_amount_display"]
        print_rows = [dict(zip(field_names, row)) for row in self._rows]
        company = session.current_company
        date_range_label = (
            f"از {numerals.format_jalali_date(self.date_from.date())} "
            f"تا {numerals.format_jalali_date(self.date_to.date())}"
        )
        footer = self._footer or ["", "", "", ""]
        params = {
            "companyName": company.display_name if company else "",
            "dateRangeLabel": date_range_label,
            "generatedAt": numerals.format_jalali_datetime(datetime.datetime.now()),
            "netIncomeLabel": footer[1],
            "netIncomeDisplay": footer[3],
        }
        return print_rows, params
