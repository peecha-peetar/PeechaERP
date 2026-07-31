"""مقایسه‌یِ دوره‌ای (ماه‌به‌ماه/فصل‌به‌فصل/سال‌به‌سال) — گردشِ حساب‌هایِ
درآمد/هزینه در چند دوره‌یِ متوالیِ جلالی، کنارِ هم."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtWidgets import QComboBox, QLabel, QSpinBox

from peecha.services import reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase, code_in_range

_GRANULARITY_OPTIONS = [("MONTHLY", "ماهانه"), ("QUARTERLY", "فصلی"), ("YEARLY", "سالانه")]


class PeriodComparisonScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("مقایسه‌یِ دوره‌ای")

        hint = QLabel("«از تاریخ» در این گزارش استفاده نمی‌شود؛ «تا تاریخ» پایانِ آخرین دوره است.")
        hint.setObjectName("sectionHint")
        self.layout().insertWidget(1, hint)

        self.extra_filter_row.addWidget(QLabel("دانه‌بندی:"))
        self.granularity_combo = QComboBox()
        for value, label in _GRANULARITY_OPTIONS:
            self.granularity_combo.addItem(label, value)
        self.granularity_combo.setCurrentIndex(0)
        self.extra_filter_row.addWidget(self.granularity_combo)

        self.extra_filter_row.addWidget(QLabel("تعدادِ دوره:"))
        self.period_count_spin = QSpinBox()
        self.period_count_spin.setRange(2, 12)
        self.period_count_spin.setValue(6)
        self.extra_filter_row.addWidget(self.period_count_spin)

        self.enable_code_range_filter()

        self.add_field_help([
            (
                self.granularity_combo,
                "هر دوره‌یِ مقایسه چقدر طول بکشد: یک ماه، یک فصل یا یک سال.",
            ),
            (
                self.period_count_spin,
                "چند دوره‌یِ متوالی کنارِ هم مقایسه شود، مثلاً ۶ ماهِ اخیر. توجه: «از تاریخ» در این گزارش استفاده نمی‌شود؛ «تا تاریخ» پایانِ آخرین دوره است.",
            ),
        ])

        self._currency_decimal_places = 0

    def extra_filters_summary(self) -> list[tuple[str, str]]:
        return [
            ("دانه‌بندی", self.granularity_combo.currentText()),
            ("تعدادِ دوره", str(self.period_count_spin.value())),
        ]

    def code_range_account_level(self) -> int | None:
        # ردیف‌هایِ این گزارش همیشه حساب‌هایِ سطحِ گروه (رول‌آپ‌شده) هستند.
        return 1

    def _fmt(self, value: decimal.Decimal) -> str:
        return f"{value:,.0f}"

    def load_report(self, company_id: int, date_from: datetime.date, date_to: datetime.date):
        granularity = self.granularity_combo.currentData()
        count = self.period_count_spin.value()
        periods = reports_service.generate_jalali_periods(date_to, granularity, count)
        result = reports_service.compute_period_comparison(
            company_id, periods, status_filter=self.status_filter()
        )
        code_from, code_to = self.code_range()

        headers = ["کد", "نام", *result.period_labels]
        rows: list[list] = []
        self._all_row_bold = []
        for r in result.rows:
            if not code_in_range(r.full_code, code_from, code_to):
                continue
            rows.append([r.full_code, r.name, *[self._fmt(a) for a in r.amounts]])
            self._all_row_bold.append(False)

        rows.append(["", "سودِ (زیانِ) خالص", *[self._fmt(a) for a in result.net_income_by_period]])
        self._all_row_bold.append(True)

        return headers, rows, None
