"""گزارشِ فروش بر اساسِ کانال -- طبقِ بازخوردِ صریحِ کاربر («امکاناتِ
حیاتیِ PeechaSync -- گزارشِ فروشِ اینترنتی بر اساسِ کانال»): برخلافِ
گزارشِ فروشِ کالا-محور، این گزارش نشان می‌دهد چه سهمی از فروش از هر
کانال (POS/عمده/اینترنتی/نماینده/مارکت‌پلیس) آمده."""

from __future__ import annotations

import datetime
import decimal

from peecha import numerals, session
from peecha.services import commercial_documents as documents_service
from peecha.services import currencies as currencies_service
from peecha.ui.screens.reports_common import ReportScreenBase

_ZERO = decimal.Decimal("0")
_CHANNEL_TYPE_LABELS = {
    "POS": "حضوری", "WHOLESALE": "عمده", "ONLINE": "اینترنتی", "AGENT": "نماینده", "MARKETPLACE": "مارکت‌پلیس",
    "PRE_SALES": "پخشِ سرد", "VAN_SALES": "پخشِ گرم",
}


class SalesReportByChannelScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("گزارشِ فروش بر اساسِ کانال")
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
        rows = documents_service.compute_sales_report_by_channel(company_id, date_from, date_to)

        headers = ["کانال", "نوعِ کانال", "تعدادِ فاکتور", "تعدادِ فروخته‌شده", "فروشِ خالص"]
        table_rows = [
            [
                r.channel_name,
                _CHANNEL_TYPE_LABELS.get(r.channel_type_code, r.channel_type_code or "—"),
                numerals.to_persian_digits(str(r.invoice_count)),
                numerals.format_money(r.quantity_sold, 2),
                self._fmt(r.net_revenue),
            ]
            for r in rows
        ]

        total_invoices = sum((r.invoice_count for r in rows), 0)
        total_quantity = sum((r.quantity_sold for r in rows), _ZERO)
        total_revenue = sum((r.net_revenue for r in rows), _ZERO)
        footer = [
            "جمعِ کل", "",
            numerals.to_persian_digits(str(total_invoices)), numerals.format_money(total_quantity, 2),
            self._fmt(total_revenue),
        ]
        return headers, table_rows, footer
