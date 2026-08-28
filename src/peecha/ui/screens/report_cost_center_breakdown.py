"""گزارشِ مرکزِ هزینه و پروژه — طبقِ درخواستِ صریح («نشان دهد در کدام
حساب‌ها مرکزِ هزینه و پروژه در سطوحِ مختلف گردش داشتن، مثلِ گزارشِ
تفصیلی») — دقیقاً همان منطقِ compute_detail_account_breakdown که برایِ
«تراز تفصیلی» ساخته شد، این‌بار مستقیماً محدود به دو نوع‌بُعدِ مرکزِ
هزینه/پروژه (به‌جایِ انتخابِ دستیِ نوع‌بُعد در گزارشِ تراز) — با یک
گزینه‌یِ «همه‌یِ مراکزِ هزینه و پروژه با هم» تا نیازی به دو بار اجرا
نباشد."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtWidgets import QComboBox, QLabel

from peecha import numerals, session
from peecha.services import currencies as currencies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase, code_in_range

_ZERO = decimal.Decimal("0")
_ALL_COST_CENTERS_PROJECTS = 0
_GL_LEVEL_OPTIONS = [(3, "معین"), (2, "کل"), (1, "گروه")]


class CostCenterBreakdownScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("گزارشِ مرکزِ هزینه و پروژه")

        self.extra_filter_row.addWidget(QLabel("مرکزِ هزینه/پروژه:"))
        self.dimension_combo = QComboBox()
        self.extra_filter_row.addWidget(self.dimension_combo)

        self.extra_filter_row.addWidget(QLabel("سطحِ حساب:"))
        self.gl_level_combo = QComboBox()
        for lvl, label in _GL_LEVEL_OPTIONS:
            self.gl_level_combo.addItem(label, lvl)
        self.gl_level_combo.currentIndexChanged.connect(self._on_gl_level_changed)
        self.extra_filter_row.addWidget(self.gl_level_combo)

        self.enable_code_range_filter()
        self.enable_document_no_filter()

        self.add_field_help([
            (
                self.dimension_combo,
                "کدام نوع‌بُعد نشان داده شود: مرکزِ هزینه، پروژه، یا هردو با هم.",
            ),
            (
                self.gl_level_combo,
                "گردشِ هر مرکزِ هزینه/پروژه در سطحِ گروه، کل یا معین به‌تفکیک نشان داده شود.",
            ),
        ])

        self._currency_decimal_places = 0
        self._cost_center_type_id: int | None = None
        self._project_type_id: int | None = None

    def code_range_account_level(self) -> int | None:
        return self.gl_level_combo.currentData()

    def _on_gl_level_changed(self) -> None:
        if self.code_from_field.isVisibleTo(self):
            self._reload_code_range_options()

    def _reload_dimension_options(self) -> None:
        company_id = self._company_id()
        self.dimension_combo.clear()
        if company_id is None:
            self._cost_center_type_id = self._project_type_id = None
            return
        self._cost_center_type_id = dimensions_service.get_specialized_dimension_type_id(
            company_id, dimensions_service.COST_CENTER_CODE
        )
        self._project_type_id = dimensions_service.get_specialized_dimension_type_id(
            company_id, dimensions_service.PROJECT_CODE
        )
        self.dimension_combo.addItem("— هردو با هم —", _ALL_COST_CENTERS_PROJECTS)
        if self._cost_center_type_id is not None:
            self.dimension_combo.addItem("مرکزِ هزینه", self._cost_center_type_id)
        if self._project_type_id is not None:
            self.dimension_combo.addItem("پروژه", self._project_type_id)

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

    def _fmt(self, value: decimal.Decimal) -> str:
        return numerals.format_money(value, self._currency_decimal_places, None)

    def load_report(self, company_id: int, date_from: datetime.date, date_to: datetime.date):
        dimension_selection = self.dimension_combo.currentData()
        if dimension_selection is None:
            return [], [], None
        gl_level = self.gl_level_combo.currentData()
        code_from, code_to = self.code_range()
        document_no_from, document_no_to = self.document_no_range()
        status_filter = self.status_filter()

        type_ids = (
            [t for t in (self._cost_center_type_id, self._project_type_id) if t is not None]
            if dimension_selection == _ALL_COST_CENTERS_PROJECTS
            else [dimension_selection]
        )

        rows: list[reports_service.DetailAccountBreakdownRow] = []
        for type_id in type_ids:
            rows.extend(
                reports_service.compute_detail_account_breakdown(
                    company_id,
                    type_id,
                    date_from,
                    date_to,
                    gl_level=gl_level,
                    status_filter=status_filter,
                    document_no_from=document_no_from,
                    document_no_to=document_no_to,
                )
            )
        rows = [r for r in rows if code_in_range(r.detail_full_code, code_from, code_to)]
        rows.sort(key=lambda r: (r.detail_full_code, r.account_full_code))

        headers = ["کدِ مرکزِ هزینه/پروژه", "نام", "کدِ حساب", "نامِ حساب", "گردش (بد)", "گردش (بس)"]
        table_rows = [
            [r.detail_full_code, r.detail_name, r.account_full_code, r.account_name, self._fmt(r.debit), self._fmt(r.credit)]
            for r in rows
        ]
        total_debit = sum((r.debit for r in rows), _ZERO)
        total_credit = sum((r.credit for r in rows), _ZERO)
        footer = ["", "", "", "جمعِ کل", self._fmt(total_debit), self._fmt(total_credit)]
        return headers, table_rows, footer
