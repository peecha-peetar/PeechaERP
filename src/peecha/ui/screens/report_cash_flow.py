"""صورتِ گردشِ وجوهِ نقد — روشِ مستقیم (از رویِ حساب‌هایِ نیازمندِ بُعدِ
صندوق/بانک) یا روشِ غیرمستقیم (از سودِ خالص + تعدیلِ حساب‌هایِ برچسب‌خورده
با بخشِ گردشِ وجوهِ نقد در «نگاشتِ صورت‌هایِ مالی»)."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtWidgets import QComboBox, QLabel

from peecha import numerals, session
from peecha.services import currencies as currencies_service
from peecha.services import reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase

_METHOD_OPTIONS = [("DIRECT", "مستقیم"), ("INDIRECT", "غیرمستقیم")]


class CashFlowScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("صورتِ گردشِ وجوهِ نقد")
        self.enable_cost_center_filter()
        self.enable_document_no_filter()

        self.extra_filter_row.addWidget(QLabel("روش:"))
        self.method_combo = QComboBox()
        for value, label in _METHOD_OPTIONS:
            self.method_combo.addItem(label, value)
        self.method_combo.currentIndexChanged.connect(self._on_method_changed)
        self.extra_filter_row.addWidget(self.method_combo)

        self._currency_decimal_places = 0

    def _on_method_changed(self) -> None:
        # فیلترِ مرکزِ هزینه/شماره‌یِ سند فقط رویِ روشِ مستقیم (که سطرهایِ
        # سندی نمایش می‌دهد) معنا دارد؛ روشِ غیرمستقیم رویِ گردشِ حساب‌هایِ
        # برچسب‌خورده کار می‌کند، نه ردیف‌هایِ تکِ سند.
        is_direct = self.method_combo.currentData() == "DIRECT"
        for widget in (
            self.cost_center_label,
            self.cost_center_combo,
            self.document_no_label,
            self.document_no_field,
        ):
            widget.setVisible(is_direct)

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
        if self.method_combo.currentData() == "INDIRECT":
            return self._load_indirect(company_id, date_from, date_to)
        return self._load_direct(company_id, date_from, date_to)

    def _load_direct(self, company_id: int, date_from: datetime.date, date_to: datetime.date):
        opening_balance, lines = reports_service.compute_cash_flow_direct(
            company_id,
            date_from,
            date_to,
            status_filter=self.status_filter(),
            cost_center_id=self.cost_center_id(),
            document_no_filter=self.document_no(),
        )

        headers = ["تاریخ", "شماره‌یِ سند", "شرح", "طرفِ حساب", "دریافت", "پرداخت"]
        rows: list[list] = [["", "", "مانده‌ی نقدِ اول", "", "", self._fmt(opening_balance)]]
        total_receipt = decimal.Decimal(0)
        total_payment = decimal.Decimal(0)
        for ln in lines:
            total_receipt += ln.receipt
            total_payment += ln.payment
            rows.append(
                [
                    numerals.format_jalali_date(ln.document_date),
                    str(ln.temporary_no),
                    ln.description or "—",
                    ln.counter_account_name,
                    self._fmt(ln.receipt) if ln.receipt else "",
                    self._fmt(ln.payment) if ln.payment else "",
                ]
            )
        closing_balance = opening_balance + total_receipt - total_payment
        rows.append(["", "", "مانده‌ی نقدِ آخر", "", "", self._fmt(closing_balance)])
        footer = ["", "", "جمعِ گردش", "", self._fmt(total_receipt), self._fmt(total_payment)]
        return headers, rows, footer

    def _load_indirect(self, company_id: int, date_from: datetime.date, date_to: datetime.date):
        result = reports_service.compute_cash_flow_indirect(
            company_id, date_from, date_to, status_filter=self.status_filter()
        )

        headers = ["کد", "شرح", "مبلغ"]
        rows: list[list] = [["", "سودِ (زیانِ) خالص", self._fmt(result.net_income)]]

        rows.append(["", "فعالیت‌هایِ عملیاتی", ""])
        for r in result.operating_rows:
            rows.append([r.full_code, r.name, self._fmt(r.amount)])
        rows.append(["", "خالصِ ورودی/خروجیِ نقدِ عملیاتی", self._fmt(result.net_operating)])

        rows.append(["", "فعالیت‌هایِ سرمایه‌گذاری", ""])
        for r in result.investing_rows:
            rows.append([r.full_code, r.name, self._fmt(r.amount)])
        rows.append(["", "خالصِ ورودی/خروجیِ نقدِ سرمایه‌گذاری", self._fmt(result.net_investing)])

        rows.append(["", "فعالیت‌هایِ تامینِ مالی", ""])
        for r in result.financing_rows:
            rows.append([r.full_code, r.name, self._fmt(r.amount)])
        rows.append(["", "خالصِ ورودی/خروجیِ نقدِ تامینِ مالی", self._fmt(result.net_financing)])

        footer = ["", "خالصِ تغییرِ وجهِ نقد", self._fmt(result.net_change_in_cash)]
        return headers, rows, footer
