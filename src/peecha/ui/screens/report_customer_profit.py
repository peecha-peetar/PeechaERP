"""گزارشِ سودِ واقعیِ مشتریان -- طبقِ درخواستِ صریحِ کاربر: برخلافِ حاشیهٔ
سودِ نظری/تعرفه‌ای (که در دیالوگِ ردیفِ فاکتور نمایش داده می‌شود)، این
گزارش سودِ *واقعاً محقق‌شده* هر مشتری را طبقِ فاکتورهایِ ثبت‌نهایی‌شده و
بهایِ تمام‌شدهٔ واقعیِ کالایِ خارج‌شده (نه بهایِ لحظه‌ای/تخمینی) نشان
می‌دهد -- تا مشخص شود کدام مشتری واقعاً سودآور است، نه صرفاً پرفروش."""

from __future__ import annotations

import datetime
import decimal

from peecha import numerals, session
from peecha.services import commercial_documents as documents_service
from peecha.services import currencies as currencies_service
from peecha.ui.screens.reports_common import ReportScreenBase

_ZERO = decimal.Decimal("0")


class CustomerProfitScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("سودِ واقعیِ مشتریان")
        self._currency_decimal_places = 0
        self.add_field_help([])

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
        rows = documents_service.compute_customer_profit(company_id, date_from, date_to)

        headers = [
            "مشتری", "تعدادِ فاکتور", "فروشِ خالص", "بهایِ تمام‌شده", "سودِ ناخالص", "حاشیهٔ سود٪",
        ]
        table_rows = [
            [
                r.customer_name,
                numerals.to_persian_digits(str(r.invoice_count)),
                self._fmt(r.net_revenue),
                self._fmt(r.cogs),
                self._fmt(r.gross_profit),
                numerals.format_money(r.margin_percent, 1) + "٪" if r.margin_percent is not None else "—",
            ]
            for r in rows
        ]

        total_invoices = sum((r.invoice_count for r in rows), 0)
        total_revenue = sum((r.net_revenue for r in rows), _ZERO)
        total_cogs = sum((r.cogs for r in rows), _ZERO)
        total_profit = sum((r.gross_profit for r in rows), _ZERO)
        total_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else None
        footer = [
            "جمعِ کل", numerals.to_persian_digits(str(total_invoices)),
            self._fmt(total_revenue), self._fmt(total_cogs), self._fmt(total_profit),
            numerals.format_money(total_margin, 1) + "٪" if total_margin is not None else "—",
        ]
        return headers, table_rows, footer
