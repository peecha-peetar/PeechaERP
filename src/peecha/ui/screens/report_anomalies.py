"""تشخیصِ سندهایِ ناقص/آنومالی — چهار بررسیِ مشخص (نه یک موتورِ AI مبهم):
اسنادِ موقتِ معوق، سندهایِ بدونِ شرح، احتمالِ سندِ تکراری، تراکنشِ
نامتعارفِ آماری."""

from __future__ import annotations

import datetime

from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QLabel, QSpinBox

from peecha import numerals
from peecha.services import reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase


class AnomaliesScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("تشخیصِ سندهایِ ناقص/آنومالی")

        self.extra_filter_row.addWidget(QLabel("آستانه‌یِ روزِ پیش‌نویسِ معوق:"))
        self.stale_days_spin = QSpinBox()
        self.stale_days_spin.setRange(1, 90)
        self.stale_days_spin.setValue(7)
        self.extra_filter_row.addWidget(self.stale_days_spin)

        self.outlier_checkbox = QCheckBox("تشخیصِ تراکنشِ نامتعارف")
        self.outlier_checkbox.setChecked(True)
        self.extra_filter_row.addWidget(self.outlier_checkbox)

        self.extra_filter_row.addWidget(QLabel("ضریبِ آستانه (Z):"))
        self.outlier_z_spin = QDoubleSpinBox()
        self.outlier_z_spin.setRange(1.0, 5.0)
        self.outlier_z_spin.setSingleStep(0.5)
        self.outlier_z_spin.setValue(3.0)
        self.extra_filter_row.addWidget(self.outlier_z_spin)

    def load_report(self, company_id: int, date_from: datetime.date, date_to: datetime.date):
        anomalies = reports_service.detect_document_anomalies(
            company_id,
            date_from,
            date_to,
            stale_draft_days=self.stale_days_spin.value(),
            detect_outliers=self.outlier_checkbox.isChecked(),
            outlier_z=self.outlier_z_spin.value(),
        )

        headers = ["نوع", "تاریخ", "شماره‌یِ سند", "شرح", "جزئیات"]
        rows: list[list] = []
        self._all_row_bold = []

        grouped: dict[str, list] = {}
        order: list[str] = []
        for a in anomalies:
            if a.kind_label not in grouped:
                grouped[a.kind_label] = []
                order.append(a.kind_label)
            grouped[a.kind_label].append(a)

        for kind_label in order:
            items = grouped[kind_label]
            rows.append([f"{kind_label} ({len(items)} مورد)", "", "", "", ""])
            self._all_row_bold.append(True)
            for a in items:
                rows.append(
                    [
                        "",
                        numerals.format_jalali_date(a.document_date) if a.document_date else "",
                        str(a.temporary_no) if a.temporary_no is not None else "",
                        a.description,
                        a.detail,
                    ]
                )
                self._all_row_bold.append(False)

        footer = ["جمعِ کل", "", "", "", f"{len(anomalies)} مورد"] if anomalies else None
        return headers, rows, footer
