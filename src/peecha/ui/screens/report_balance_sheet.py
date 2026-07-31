"""ترازنامه — دارایی‌ها/بدهی‌ها/حقوقِ صاحبانِ سهام تا یک تاریخِ مشخص
(«تا تاریخ» در نوارِ فیلترِ مشترک به‌عنوانِ تاریخِ ترازنامه استفاده می‌شود؛
«از تاریخ» در این گزارش اثری ندارد، چون ترازنامه مانده‌یِ تجمعی است، نه
گردشِ یک بازه)."""

from __future__ import annotations

import datetime
import decimal

from peecha import numerals, session
from peecha.services import currencies as currencies_service
from peecha.services import reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase, code_in_range


class BalanceSheetScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("ترازنامه (تا «تا تاریخ»)")
        self.enable_code_range_filter()
        self.enable_cost_center_filter()
        self._currency_decimal_places = 0

    def code_range_account_level(self) -> int | None:
        # ردیف‌هایِ ترازنامه همیشه حساب‌هایِ سطحِ کل (رول‌آپ‌شده) هستند.
        return 2

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
        result = reports_service.compute_balance_sheet(
            company_id, date_to, status_filter=self.status_filter(), cost_center_id=self.cost_center_id()
        )

        def in_range(r):
            return code_in_range(r.full_code, code_from, code_to)

        asset_rows = [r for r in result.asset_rows if in_range(r)]
        liability_rows = [r for r in result.liability_rows if in_range(r)]
        equity_rows = [r for r in result.equity_rows if in_range(r)]
        total_assets = sum((r.balance for r in asset_rows), decimal.Decimal(0))
        total_liabilities = sum((r.balance for r in liability_rows), decimal.Decimal(0))
        total_equity = sum((r.balance for r in equity_rows), decimal.Decimal(0)) + result.accumulated_earnings

        headers = ["کد", "نام", "مبلغ"]
        rows: list[list] = []
        rows.append(["", "دارایی‌ها", ""])
        for r in asset_rows:
            rows.append([r.full_code, r.name, self._fmt(r.balance)])
        rows.append(["", "جمعِ دارایی‌ها", self._fmt(total_assets)])

        rows.append(["", "بدهی‌ها", ""])
        for r in liability_rows:
            rows.append([r.full_code, r.name, self._fmt(r.balance)])
        rows.append(["", "جمعِ بدهی‌ها", self._fmt(total_liabilities)])

        rows.append(["", "حقوقِ صاحبانِ سهام", ""])
        for r in equity_rows:
            rows.append([r.full_code, r.name, self._fmt(r.balance)])
        rows.append(["", "سودِ (زیانِ) انباشته", self._fmt(result.accumulated_earnings)])
        rows.append(["", "جمعِ حقوقِ صاحبانِ سهام", self._fmt(total_equity)])

        footer = ["", "جمعِ بدهی‌ها + حقوقِ صاحبانِ سهام", self._fmt(total_liabilities + total_equity)]
        return headers, rows, footer
