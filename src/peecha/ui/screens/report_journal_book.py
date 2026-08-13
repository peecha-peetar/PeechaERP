"""دفتر روزنامه — فهرستِ سند+سطر به‌ترتیبِ تاریخ/شماره، با کدهایِ حسابِ
استانداردِ کنارِ نامِ حساب و شرحِ سند/سطر، برایِ تحریرِ دفاترِ قانونی."""

from __future__ import annotations

import datetime
import decimal

from peecha import numerals, session
from peecha.services import currencies as currencies_service
from peecha.services import reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase, code_in_range


class JournalBookScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("دفتر روزنامه")
        self.enable_code_range_filter()
        self.enable_cost_center_filter()
        self.enable_document_no_filter()
        self._currency_decimal_places = 0

    def code_range_account_level(self) -> int | None:
        # سطرهایِ دفترِ روزنامه همیشه رویِ حساب‌هایِ قابلِ‌ثبتِ سند (سطحِ معین) هستند.
        return 3

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

    def load_report(self, company_id: int, date_from: datetime.date, date_to: datetime.date):
        code_from, code_to = self.code_range()
        document_no_from, document_no_to = self.document_no_range()
        lines = reports_service.list_journal_book_lines(
            company_id,
            date_from,
            date_to,
            status_filter=self.status_filter(),
            cost_center_id=self.cost_center_id(),
            document_no_from=document_no_from,
            document_no_to=document_no_to,
        )
        lines = [ln for ln in lines if code_in_range(ln.account_full_code, code_from, code_to)]

        def fmt(value: decimal.Decimal) -> str:
            return numerals.format_money(value, self._currency_decimal_places, None)

        headers = [
            "تاریخ", "شماره‌یِ سند", "کدِ حساب", "نامِ حساب", "تفصیلی", "مرکزِ هزینه", "پروژه", "شرح", "بدهکار", "بستانکار",
        ]
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
                    ln.detail_name or "—",
                    ln.cost_center_name or "—",
                    ln.project_name or "—",
                    ln.description or "—",
                    fmt(ln.debit) if ln.debit else "",
                    fmt(ln.credit) if ln.credit else "",
                ]
            )
        footer = ["", "", "", "", "", "", "", "جمعِ کل", fmt(total_debit), fmt(total_credit)]
        return headers, rows, footer
