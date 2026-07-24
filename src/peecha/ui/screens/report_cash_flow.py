"""صورتِ گردشِ وجوهِ نقد — روشِ مستقیم (از رویِ حساب‌هایِ نیازمندِ بُعدِ
صندوق/بانک). روشِ غیرمستقیم پیاده نشده — نیازمندِ طبقه‌بندیِ عملیاتی/
سرمایه‌گذاری/تامینِ مالی است که امروز رویِ حساب‌ها وجود ندارد."""

from __future__ import annotations

import datetime
import decimal

from peecha import numerals, session
from peecha.services import currencies as currencies_service
from peecha.services import reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase


class CashFlowScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("صورتِ گردشِ وجوهِ نقد (روشِ مستقیم)")
        self.enable_cost_center_filter()
        self.enable_document_no_filter()
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
        opening_balance, lines = reports_service.compute_cash_flow_direct(
            company_id,
            date_from,
            date_to,
            status_filter=self.status_filter(),
            cost_center_id=self.cost_center_id(),
            document_no_filter=self.document_no(),
        )

        headers = ["تاریخ", "شماره‌یِ سند", "شرح", "طرفِ حساب", "دریافت", "پرداخت"]
        rows: list[list] = [["", "", "مانده‌ی نقدِ اول", "", "", self._fmt(opening_balance)]]
        total_receipt = decimal.Decimal(0)
        total_payment = decimal.Decimal(0)
        for ln in lines:
            total_receipt += ln.receipt
            total_payment += ln.payment
            rows.append(
                [
                    numerals.format_jalali_date(ln.document_date),
                    str(ln.temporary_no),
                    ln.description or "—",
                    ln.counter_account_name,
                    self._fmt(ln.receipt) if ln.receipt else "",
                    self._fmt(ln.payment) if ln.payment else "",
                ]
            )
        closing_balance = opening_balance + total_receipt - total_payment
        rows.append(["", "", "مانده‌ی نقدِ آخر", "", "", self._fmt(closing_balance)])
        footer = ["", "", "جمعِ گردش", "", self._fmt(total_receipt), self._fmt(total_payment)]
        return headers, rows, footer
