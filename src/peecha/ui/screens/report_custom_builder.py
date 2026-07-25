"""اجرایِ یک گزارشِ ساخته‌شده با «گزارش‌سازِ کامل» (report_designer.py) —
این صفحه فقط یک گزارش را انتخاب و برایِ بازه‌یِ تاریخِ دلخواه اجرا می‌کند؛
بسته به نوعِ گزارش (تراکنشی/خلاصه)، ستون‌ها کاملاً پویا هستند — headers از
خودِ الگو می‌آید، هر سلول بر اساسِ kind خودش (TEXT/MONEY/DATE) قالب‌بندی
می‌شود."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtWidgets import QComboBox, QLabel

from peecha import numerals, session
from peecha.services import currencies as currencies_service
from peecha.services import report_designer as report_designer_service
from peecha.services import reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase


class ReportBuilderRunScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("گزارش‌سازِ کامل (اجرا)")
        self.enable_cost_center_filter()
        self.enable_document_no_filter()

        self.extra_filter_row.addWidget(QLabel("گزارش:"))
        self.template_combo = QComboBox()
        self.template_combo.currentIndexChanged.connect(self._on_template_changed)
        self.extra_filter_row.addWidget(self.template_combo)

        self.add_field_help([
            (
                self.template_combo,
                "گزارشی که می‌خواهید اجرا کنید. گزارش‌ها در «گزارش‌سازِ کامل» ساخته می‌شوند؛ "
                "این صفحه فقط آن‌ها را برایِ بازه‌یِ تاریخِ دلخواه اجرا می‌کند.",
            ),
        ])

        self._currency_decimal_places = 0
        self._templates: list[report_designer_service.ReportTemplateRow] = []

    def extra_filters_summary(self) -> list[tuple[str, str]]:
        return [("گزارش", self.template_combo.currentText())]

    def _selected_template(self) -> report_designer_service.ReportTemplateRow | None:
        template_id = self.template_combo.currentData()
        return next((t for t in self._templates if t.report_template_id == template_id), None)

    def _on_template_changed(self) -> None:
        template = self._selected_template()
        is_detail = template is not None and template.report_kind == "DETAIL"
        for widget in (
            self.cost_center_label,
            self.cost_center_combo,
            self.document_no_label,
            self.document_no_field,
        ):
            widget.setVisible(is_detail)

    def refresh(self) -> None:
        company = session.current_company
        currency = None
        if company is not None:
            currency = next(
                (c for c in currencies_service.list_all_currencies() if c.currency_id == company.base_currency_id),
                None,
            )
        self._currency_decimal_places = currency.decimal_places if currency else 0

        company_id = self._company_id()
        self._templates = report_designer_service.list_templates(company_id) if company_id is not None else []
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        for t in self._templates:
            self.template_combo.addItem(t.name, t.report_template_id)
        self.template_combo.blockSignals(False)
        self._on_template_changed()
        super().refresh()

    def _fmt_money(self, value: decimal.Decimal) -> str:
        return numerals.format_money(value, self._currency_decimal_places, None)

    def _fmt_cell(self, cell: reports_service.ReportCell) -> str:
        if cell.value is None:
            return ""
        if cell.kind == "MONEY":
            return self._fmt_money(cell.value)
        if cell.kind == "DATE":
            return numerals.format_jalali_date(cell.value)
        return str(cell.value)

    def load_report(self, company_id: int, date_from: datetime.date, date_to: datetime.date):
        template = self._selected_template()
        if template is None:
            return [], [], None

        if template.report_kind == "DETAIL":
            headers, report_rows = reports_service.compute_detail_report(
                template.report_template_id,
                company_id,
                date_from,
                date_to,
                status_filter=self.status_filter(),
                cost_center_id=self.cost_center_id(),
                document_no_filter=self.document_no(),
            )
        else:
            headers, report_rows = reports_service.compute_summary_report(
                template.report_template_id, company_id, date_from, date_to, status_filter=self.status_filter()
            )

        rows: list[list] = []
        self._all_row_bold = []
        for r in report_rows:
            rows.append([self._fmt_cell(c) for c in r.cells])
            self._all_row_bold.append(r.is_bold)

        return headers, rows, None
