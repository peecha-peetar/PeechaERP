"""دفتر کل/معین/تفصیلی + مرورِ حساب‌ها — یک صفحه‌یِ مشترک، چون هرسه گزارش
از نظرِ داده یکی‌اند: فقط سطحِ فیلتر فرق دارد.

دو حالت:
- «خلاصه»: همان جدولِ ماندهِ تراز آزمایشی (سطحِ گروه/کل/معین/تفصیلی)؛
  دابل‌کلیک رویِ ردیفِ گروه/کل به فرزندانش Drill-down می‌کند (مرورِ حساب‌ها).
- «گردشِ حساب»: با دابل‌کلیک رویِ ردیفِ معین یا تفصیلی، گردشِ زمانیِ همان یک
  حساب (دفتر کل/معین/تفصیلی) با مانده‌یِ رواگرد نمایش داده می‌شود."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtWidgets import QComboBox, QLabel, QPushButton

from peecha import numerals, session
from peecha.services import currencies as currencies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import reports as reports_service
from peecha.ui.screens.reports_common import ReportScreenBase, code_in_range, dimension_label, net_split

_ZERO = decimal.Decimal("0")
_LEVEL_OPTIONS = [(1, "گروه"), (2, "کل"), (3, "معین"), (4, "تفصیلی")]


class AccountLedgerScreen(ReportScreenBase):
    def __init__(self) -> None:
        super().__init__("دفتر کل / معین / تفصیلی — مرورِ حساب‌ها")

        self.extra_filter_row.addWidget(QLabel("سطح:"))
        self.level_combo = QComboBox()
        for level, label in _LEVEL_OPTIONS:
            self.level_combo.addItem(label, level)
        self.level_combo.setCurrentIndex(0)
        self.level_combo.currentIndexChanged.connect(self._on_level_changed)
        self.extra_filter_row.addWidget(self.level_combo)

        self.dimension_label = QLabel("نوعِ تفصیلی:")
        self.dimension_label.setVisible(False)
        self.extra_filter_row.addWidget(self.dimension_label)
        self.dimension_combo = QComboBox()
        self.dimension_combo.setVisible(False)
        self.extra_filter_row.addWidget(self.dimension_combo)

        self.back_button = QPushButton("↩ بازگشت به فهرست")
        self.back_button.setObjectName("flatButton")
        self.back_button.setVisible(False)
        self.back_button.clicked.connect(self._go_back)
        self.extra_filter_row.addWidget(self.back_button)

        self.enable_code_range_filter()
        self.enable_cost_center_filter()
        self.enable_document_no_filter()

        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)

        self._mode = "summary"
        self._parent_id: int | None = None
        self._ledger_target: tuple[str, int, str] | None = None
        self._currency_decimal_places = 0

    def _on_level_changed(self) -> None:
        is_detail = self.level_combo.currentData() == 4
        self.dimension_label.setVisible(is_detail)
        self.dimension_combo.setVisible(is_detail)
        if is_detail and self.dimension_combo.count() == 0:
            self._reload_dimension_options()
        self._reset_drill()

    def _reset_drill(self) -> None:
        self._mode = "summary"
        self._parent_id = None
        self._ledger_target = None
        self.back_button.setVisible(False)

    def _go_back(self) -> None:
        self._reset_drill()
        self.level_combo.blockSignals(True)
        self.level_combo.setCurrentIndex(0)
        self.level_combo.blockSignals(False)
        self.dimension_label.setVisible(False)
        self.dimension_combo.setVisible(False)
        self._reload()

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
        self._reset_drill()
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

    def _on_row_double_clicked(self, row: int, _column: int) -> None:
        if row >= len(self._row_ids):
            return
        row_id = self._row_ids[row]
        if self._mode == "ledger":
            return
        level = self.level_combo.currentData()
        if level in (1, 2):
            next_index = next(i for i, (lv, _label) in enumerate(_LEVEL_OPTIONS) if lv == level + 1)
            self.level_combo.blockSignals(True)
            self.level_combo.setCurrentIndex(next_index)
            self.level_combo.blockSignals(False)
            self._parent_id = row_id
            self.back_button.setVisible(True)
        else:
            kind = "detail" if level == 4 else "account"
            name = self._rows[row][1] if row < len(self._rows) else ""
            self._ledger_target = (kind, row_id, name)
            self._mode = "ledger"
            self.back_button.setVisible(True)
        self._reload()

    def load_report(self, company_id: int, date_from: datetime.date, date_to: datetime.date):
        if self._mode == "ledger" and self._ledger_target is not None:
            return self._load_ledger(company_id, date_from, date_to)
        return self._load_summary(company_id, date_from, date_to)

    def _load_summary(self, company_id: int, date_from: datetime.date, date_to: datetime.date):
        level = self.level_combo.currentData()
        status_filter = self.status_filter()
        cost_center_id = self.cost_center_id()
        code_from, code_to = self.code_range()

        if level == 4:
            dimension_type_id = self.dimension_combo.currentData()
            if dimension_type_id is None:
                return [], [], None
            rows = reports_service.compute_detail_balances(
                company_id, dimension_type_id, date_from, date_to, status_filter=status_filter
            )
            if self._parent_id is not None:
                rows = [r for r in rows if r.parent_account_id == self._parent_id]
        else:
            all_rows = reports_service.compute_account_balances(
                company_id, date_from, date_to, status_filter=status_filter, cost_center_id=cost_center_id
            )
            rows = [r for r in all_rows if r.account_level == level]
            if self._parent_id is not None:
                rows = [r for r in all_rows if r.parent_account_id == self._parent_id]
        rows = [r for r in rows if code_in_range(r.full_code, code_from, code_to)]

        headers = ["کد", "نام", "مانده‌ی اول (بد)", "مانده‌ی اول (بس)", "گردش (بد)", "گردش (بس)", "مانده‌ی آخر (بد)", "مانده‌ی آخر (بس)"]
        table_rows: list[list] = []
        totals = [_ZERO] * 6
        self._all_row_ids = []
        for r in rows:
            opening_debit, opening_credit = net_split(r.opening_debit, r.opening_credit)
            closing_debit, closing_credit = net_split(r.closing_debit, r.closing_credit)
            values = [opening_debit, opening_credit, r.period_debit, r.period_credit, closing_debit, closing_credit]
            for i, v in enumerate(values):
                totals[i] += v
            table_rows.append([r.full_code, r.name, *[self._fmt(v) for v in values]])
            self._all_row_ids.append(r.account_id)

        hint = "" if self._parent_id is None else " (زیرمجموعه — دابل‌کلیکِ ردیفِ معین/تفصیلی گردشِ حساب را نشان می‌دهد)"
        footer = ["", f"جمعِ کل{hint}", *[self._fmt(v) for v in totals]]
        return headers, table_rows, footer

    def _load_ledger(self, company_id: int, date_from: datetime.date, date_to: datetime.date):
        kind, target_id, name = self._ledger_target
        kwargs = {"detail_account_id": target_id} if kind == "detail" else {"account_id": target_id}
        opening_debit, opening_credit, lines = reports_service.list_ledger_entries(
            company_id,
            date_from,
            date_to,
            status_filter=self.status_filter(),
            cost_center_id=self.cost_center_id(),
            document_no_filter=self.document_no(),
            **kwargs,
        )
        headers = ["تاریخ", "شماره‌یِ سند", "شرح", "بدهکار", "بستانکار", "مانده"]
        table_rows: list[list] = []
        opening_net = opening_debit - opening_credit
        table_rows.append(
            ["", "", f"مانده‌ی اول — {name}", "", "", self._signed(opening_net)]
        )
        total_debit = _ZERO
        total_credit = _ZERO
        for ln in lines:
            total_debit += ln.debit
            total_credit += ln.credit
            running_net = ln.running_debit - ln.running_credit
            table_rows.append(
                [
                    numerals.format_jalali_date(ln.document_date),
                    str(ln.temporary_no),
                    ln.description or "—",
                    self._fmt(ln.debit) if ln.debit else "",
                    self._fmt(ln.credit) if ln.credit else "",
                    self._signed(running_net),
                ]
            )
        self._all_row_ids = [0] * len(table_rows)
        footer = ["", "", "جمعِ گردش", self._fmt(total_debit), self._fmt(total_credit), ""]
        return headers, table_rows, footer

    def _signed(self, net: decimal.Decimal) -> str:
        if net >= 0:
            return f"{self._fmt(net)} (بد)"
        return f"{self._fmt(-net)} (بس)"
