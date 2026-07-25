"""نسبت‌هایِ مالی — سودآوری/اهرمی، رویِ compute_balance_sheet/
compute_income_statement موجود سوار می‌شود. طبقِ محدودیتِ شناخته‌شده:
نسبت‌هایِ نقدینگی (جاری/آنی) این‌جا نیستند چون تفکیکِ دارایی/بدهیِ
«جاری» در برابرِ «غیرِجاری» رویِ حساب‌ها وجود ندارد."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtWidgets import QLabel

from peecha.services import reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase


class FinancialRatiosScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("نسبت‌هایِ مالی")

        hint = QLabel(
            "نسبت‌هایِ نقدینگی (جاری/آنی) این‌جا نیستند — چون تفکیکِ دارایی/بدهیِ «جاری» در برابرِ «غیرِجاری» "
            "رویِ حساب‌ها هنوز تعریف نشده. «تا تاریخ» = تاریخِ ترازنامه؛ بازه‌یِ «از–تا تاریخ» = دوره‌یِ سود-زیان."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        self.layout().insertWidget(1, hint)

    def load_report(self, company_id: int, date_from: datetime.date, date_to: datetime.date):
        rows_data = reports_service.compute_financial_ratios(
            company_id, date_from, date_to, status_filter=self.status_filter()
        )
        headers = ["نسبت", "مقدار"]
        rows: list[list] = []
        for r in rows_data:
            if r.value is None:
                value_text = "—"
            elif r.is_percentage:
                value_text = f"{r.value * decimal.Decimal(100):,.1f}٪"
            else:
                value_text = f"{r.value:,.2f}"
            rows.append([r.label, value_text])
        return headers, rows, None
