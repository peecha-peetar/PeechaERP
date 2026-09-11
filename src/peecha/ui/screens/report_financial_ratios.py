"""نسبت‌هایِ مالی — سودآوری/اهرمی/نقدینگی، رویِ compute_balance_sheet/
compute_income_statement موجود سوار می‌شود. نسبت‌هایِ نقدینگی (جاری/آنی)
فقط برایِ حساب‌هایی محاسبه می‌شوند که «طبقه‌یِ نقدینگی»شان در کدینگِ
حسابداری/نگاشتِ صورت‌هایِ مالی تنظیم شده باشد."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtWidgets import QLabel

from peecha import numerals
from peecha.services import reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase


class FinancialRatiosScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("نسبت‌هایِ مالی")

        hint = QLabel(
            "نسبتِ جاری/آنی فقط برایِ حساب‌هایی محاسبه می‌شود که «طبقه‌یِ نقدینگی»شان در کدینگِ حسابداری یا "
            "نگاشتِ صورت‌هایِ مالی تنظیم شده باشد (جاری/جاری-موجودی برایِ دارایی، جاری برایِ بدهی)؛ اگر هیچ "
            "حسابی طبقه‌بندی نشده باشد، این دو نسبت «—» نشان داده می‌شوند. «تا تاریخ» = تاریخِ ترازنامه؛ "
            "بازه‌یِ «از–تا تاریخ» = دوره‌یِ سود-زیان."
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
            elif r.kind == "PERCENTAGE":
                value_text = numerals.to_persian_digits(f"{r.value * decimal.Decimal(100):,.1f}") + "٪"
            elif r.kind == "CURRENCY":
                value_text = numerals.format_company_amount(r.value)
            else:  # RATIO
                value_text = numerals.to_persian_digits(f"{r.value:,.2f}")
            rows.append([r.label, value_text])
        return headers, rows, None
