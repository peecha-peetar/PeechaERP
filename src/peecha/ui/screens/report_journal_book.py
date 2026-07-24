"""دفتر روزنامه — فهرستِ سند+سطر به‌ترتیبِ تاریخ/شماره، با کدهایِ حسابِ
استانداردِ کنارِ نامِ حساب و شرحِ سند/سطر، برایِ تحریرِ دفاترِ قانونی."""

from __future__ import annotations

import datetime
import decimal

from peecha import numerals, session
from peecha.services import currencies as currencies_service
from peecha.services import reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase


class JournalBookScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("دفتر روزنامه")
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

    def load_report(self, company_id: int, date_from: datetime.date, date_to: datetime.date):
        lines = reports_service.list_journal_book_lines(company_id, date_from, date_to)

        def fmt(value: decimal.Decimal) -> str:
            return numerals.format_money(value, self._currency_decimal_places, self._currency_symbol)

        headers = ["تاریخ", "شماره‌یِ سند", "کدِ حساب", "نامِ حساب", "شرح", "بدهکار", "بستانکار"]
        rows: list[list] = []
        total_debit = decimal.Decimal(0)
        total_credit = decimal.Decimal(0)
        for ln in lines:
            total_debit += ln.debit
            total_credit += ln.credit
            rows.append(
                [
                    numerals.format_jalali_date(ln.document_date),
                    str(ln.temporary_no),
                    ln.account_full_code,
                    ln.account_name,
                    ln.description or "—",
                    fmt(ln.debit) if ln.debit else "",
                    fmt(ln.credit) if ln.credit else "",
                ]
            )
        footer = ["", "", "", "", "جمعِ کل", fmt(total_debit), fmt(total_credit)]
        return headers, rows, footer
