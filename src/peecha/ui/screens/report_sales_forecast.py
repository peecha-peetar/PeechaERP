"""پیش‌بینیِ فروش -- طبقِ ادامهٔ فهرستِ درخواستی، همان اصلِ رعایت‌شده در
sales_assistant.py («بدونِ هیچ مدلِ یادگیریِ ماشین، فقط آمارِ ساده‌یِ
توصیفی»): بر اساسِ روندِ خطیِ فروشِ خالصِ N دورهٔ اخیر، فروشِ دورهٔ بعدی
تخمین زده می‌شود."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtWidgets import QComboBox, QLabel, QSpinBox

from peecha import numerals, session
from peecha.services import commercial_documents as documents_service
from peecha.services import currencies as currencies_service
from peecha.services import reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase

_GRANULARITY_OPTIONS = [("MONTHLY", "ماهانه"), ("QUARTERLY", "فصلی")]


class SalesForecastScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("پیش‌بینیِ فروش")

        hint = QLabel("«از تاریخ» در این گزارش استفاده نمی‌شود؛ «تا تاریخ» پایانِ آخرین دورهٔ واقعی است.")
        hint.setObjectName("sectionHint")
        self.layout().insertWidget(1, hint)

        self.extra_filter_row.addWidget(QLabel("دانه‌بندی:"))
        self.granularity_combo = QComboBox()
        for value, label in _GRANULARITY_OPTIONS:
            self.granularity_combo.addItem(label, value)
        self.extra_filter_row.addWidget(self.granularity_combo)

        self.extra_filter_row.addWidget(QLabel("تعدادِ دورهٔ واقعی:"))
        self.period_count_spin = QSpinBox()
        self.period_count_spin.setRange(3, 24)
        self.period_count_spin.setValue(6)
        self.extra_filter_row.addWidget(self.period_count_spin)

        self.add_field_help([
            (self.granularity_combo, "طولِ هر دوره: ماهانه یا فصلی."),
            (
                self.period_count_spin,
                "چند دورهٔ اخیر مبنایِ محاسبهٔ روند قرار بگیرد -- هرچه بیشتر، روند پایدارتر ولی کندتر به تغییرِ اخیر واکنش نشان می‌دهد.",
            ),
        ])
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
        granularity = self.granularity_combo.currentData()
        count = self.period_count_spin.value()
        periods = reports_service.generate_jalali_periods(date_to, granularity, count)
        result = documents_service.compute_sales_trend(company_id, periods)

        headers = ["دوره", "فروشِ خالص"]
        table_rows = [[label, self._fmt(amount)] for label, amount in zip(result.period_labels, result.amounts)]
        self._all_row_bold = [False] * len(table_rows)
        if result.forecast_next is not None:
            table_rows.append(["پیش‌بینی (دورهٔ بعد)", self._fmt(result.forecast_next)])
            self._all_row_bold.append(True)

        return headers, table_rows, None
