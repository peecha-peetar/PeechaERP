"""تراز آزمایشی — سطحِ گروه/کل/معین/تفصیلی، در سه حالتِ ستونی (۴/۶/۸).

تعریفِ حالت‌هایِ ستونی (طبقِ رایج‌ترین قراردادِ حسابداریِ ایران):
- ۴ ستونی: فقط گردشِ دوره (بد/بس) + مانده‌یِ آخر (بد/بس خالص) — بدونِ مانده‌یِ اول.
- ۶ ستونی: مانده‌یِ اول (بد/بس خالص) + گردشِ دوره (بد/بس) + مانده‌یِ آخر (بد/بس خالص).
- ۸ ستونی: مانده‌یِ اولِ سالِ مالی (بد/بس خالص) + گردشِ همین بازه (بد/بس) +
  گردشِ تجمعیِ از ابتدایِ سالِ مالی تا پایانِ بازه (بد/بس) + مانده‌یِ آخر (بد/بس خالص).

چون در سیستم سندِ اختتامیه‌ای وجود ندارد، «مانده‌یِ اول» همیشه یعنی جمعِ همه‌چیز
پیش از تاریخِ شروع (نه مانده‌یِ بعدِ یک بستنِ رسمی) — طبقِ محدودیتِ مستندشده در
reports.py."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtWidgets import QComboBox, QLabel

from peecha import numerals, session
from peecha.services import currencies as currencies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import fiscal_years as fiscal_years_service
from peecha.services import reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase, code_in_range, dimension_label, net_split

_ZERO = decimal.Decimal("0")

_LEVEL_OPTIONS = [(1, "گروه"), (2, "کل"), (3, "معین"), (4, "تفصیلی")]
_COLUMN_MODE_OPTIONS = [
    (6, "۶ ستونی (پیش‌فرض)"),
    (4, "۴ ستونی"),
    (8, "۸ ستونی"),
]


class TrialBalanceScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("تراز آزمایشی")

        self.extra_filter_row.addWidget(QLabel("سطح:"))
        self.level_combo = QComboBox()
        for level, label in _LEVEL_OPTIONS:
            self.level_combo.addItem(label, level)
        self.level_combo.setCurrentIndex(2)  # معین پیشِ‌فرض
        self.level_combo.currentIndexChanged.connect(self._on_level_changed)
        self.extra_filter_row.addWidget(self.level_combo)

        self.dimension_label = QLabel("نوعِ تفصیلی:")
        self.dimension_label.setVisible(False)
        self.extra_filter_row.addWidget(self.dimension_label)
        self.dimension_combo = QComboBox()
        self.dimension_combo.setVisible(False)
        self.extra_filter_row.addWidget(self.dimension_combo)

        self.extra_filter_row.addWidget(QLabel("حالتِ ستونی:"))
        self.column_mode_combo = QComboBox()
        for mode, label in _COLUMN_MODE_OPTIONS:
            self.column_mode_combo.addItem(label, mode)
        self.extra_filter_row.addWidget(self.column_mode_combo)

        self.enable_code_range_filter()
        self.enable_cost_center_filter()

        self.add_field_help([
            (
                self.level_combo,
                "گزارش تا کدام سطح خلاصه شود: گروه، کل، معین یا تفصیلی. پیش‌فرض «معین» است.",
            ),
            (
                self.dimension_combo,
                "کدام نوعِ تفصیلی (کالا، بانک، مشتری و بقیه) نشان داده شود — فقط وقتی سطح روی «تفصیلی» باشد فعال می‌شود.",
            ),
            (
                self.column_mode_combo,
                "چند ستون نشان داده شود. «۴ ستونی» فقط گردشِ دوره و مانده‌یِ آخر را دارد. "
                "«۶ ستونی» مانده‌یِ اول را هم اضافه می‌کند. «۸ ستونی» گردشِ تجمعیِ از اولِ سالِ مالی را هم نشان می‌دهد.",
            ),
        ])

        self._currency_decimal_places = 0

    def extra_filters_summary(self) -> list[tuple[str, str]]:
        parts = [("سطح", self.level_combo.currentText())]
        if self.dimension_combo.isVisibleTo(self) and self.dimension_combo.currentData() is not None:
            parts.append(("نوعِ تفصیلی", self.dimension_combo.currentText()))
        parts.append(("حالتِ ستونی", self.column_mode_combo.currentText()))
        return parts

    def code_range_account_level(self) -> int | None:
        return self.level_combo.currentData()

    def _on_level_changed(self) -> None:
        is_detail = self.level_combo.currentData() == 4
        self.dimension_label.setVisible(is_detail)
        self.dimension_combo.setVisible(is_detail)
        if is_detail and self.dimension_combo.count() == 0:
            self._reload_dimension_options()
        if self.code_from_field.isVisibleTo(self):
            self._reload_code_range_options()

    def _reload_dimension_options(self) -> None:
        company_id = self._company_id()
        self.dimension_combo.clear()
        if company_id is None:
            return
        for t in dimensions_service.list_dimension_types(company_id, include_system=True):
            if t.is_active:
                self.dimension_combo.addItem(dimension_label(t.code), t.dimension_type_id)

    def refresh(self) -> None:
        self._reload_dimension_options()
        company = session.current_company
        currency = None
        if company is not None:
            currency = next(
                (c for c in currencies_service.list_all_currencies() if c.currency_id == company.base_currency_id),
                None,
            )
        self._currency_decimal_places = currency.decimal_places if currency else 0
        super().refresh()

    def _fiscal_year_start(self, company_id: int, on_date: datetime.date) -> datetime.date | None:
        fiscal_year = fiscal_years_service.pick_current(company_id, on_date)
        return fiscal_year.start_date if fiscal_year is not None else None

    def load_report(self, company_id: int, date_from: datetime.date, date_to: datetime.date):
        level = self.level_combo.currentData()
        column_mode = self.column_mode_combo.currentData()
        dimension_type_id = self.dimension_combo.currentData() if level == 4 else None
        status_filter = self.status_filter()
        cost_center_id = self.cost_center_id()
        code_from, code_to = self.code_range()

        if level == 4:
            if dimension_type_id is None:
                return [], [], None
            period_rows = reports_service.compute_detail_balances(
                company_id, dimension_type_id, date_from, date_to, status_filter=status_filter
            )
        else:
            period_rows = [
                r
                for r in reports_service.compute_account_balances(
                    company_id, date_from, date_to, status_filter=status_filter, cost_center_id=cost_center_id
                )
                if r.account_level == level
            ]
        period_rows = [r for r in period_rows if code_in_range(r.full_code, code_from, code_to)]

        annual_by_id: dict[int, reports_service.AccountBalanceRow] = {}
        if column_mode == 8:
            year_start = self._fiscal_year_start(company_id, date_to) or date_from
            if level == 4:
                annual_rows = reports_service.compute_detail_balances(
                    company_id, dimension_type_id, year_start, date_to, status_filter=status_filter
                )
            else:
                annual_rows = [
                    r
                    for r in reports_service.compute_account_balances(
                        company_id, year_start, date_to, status_filter=status_filter, cost_center_id=cost_center_id
                    )
                    if r.account_level == level
                ]
            annual_by_id = {r.account_id: r for r in annual_rows}

        def fmt(value: decimal.Decimal) -> str:
            return numerals.format_money(value, self._currency_decimal_places, None)

        headers = ["کد", "نام"]
        if column_mode == 8:
            headers += [
                "مانده‌ی اولِ سال (بد)", "مانده‌ی اولِ سال (بس)",
                "گردشِ دوره (بد)", "گردشِ دوره (بس)",
                "گردشِ تجمعیِ سال (بد)", "گردشِ تجمعیِ سال (بس)",
                "مانده‌ی آخر (بد)", "مانده‌ی آخر (بس)",
            ]
        elif column_mode == 6:
            headers += [
                "مانده‌ی اول (بد)", "مانده‌ی اول (بس)",
                "گردش (بد)", "گردش (بس)",
                "مانده‌ی آخر (بد)", "مانده‌ی آخر (بس)",
            ]
        else:
            headers += ["گردش (بد)", "گردش (بس)", "مانده‌ی آخر (بد)", "مانده‌ی آخر (بس)"]

        table_rows: list[list] = []
        totals = [_ZERO] * (len(headers) - 2)
        for r in period_rows:
            closing_debit, closing_credit = net_split(r.closing_debit, r.closing_credit)
            if column_mode == 8:
                annual = annual_by_id.get(r.account_id)
                year_opening_debit, year_opening_credit = (
                    net_split(annual.opening_debit, annual.opening_credit) if annual else (_ZERO, _ZERO)
                )
                year_period_debit = annual.period_debit if annual else _ZERO
                year_period_credit = annual.period_credit if annual else _ZERO
                values = [
                    year_opening_debit, year_opening_credit,
                    r.period_debit, r.period_credit,
                    year_period_debit, year_period_credit,
                    closing_debit, closing_credit,
                ]
            elif column_mode == 6:
                opening_debit, opening_credit = net_split(r.opening_debit, r.opening_credit)
                values = [opening_debit, opening_credit, r.period_debit, r.period_credit, closing_debit, closing_credit]
            else:
                values = [r.period_debit, r.period_credit, closing_debit, closing_credit]

            for i, v in enumerate(values):
                totals[i] += v
            table_rows.append([r.full_code, r.name, *[fmt(v) for v in values]])

        footer = ["", "جمعِ کل", *[fmt(v) for v in totals]]
        return headers, table_rows, footer
