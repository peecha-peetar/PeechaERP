"""فرمِ واحدِ دریافت/پرداختِ چندروشی — یک طرف‌حساب + چند ردیفِ روش (نقد/
بانک/چک/تخفیف)، هرکدام طبقِ نگاشتِ تنظیماتِ خزانه‌داری به حسابِ خودش
می‌رود و همه در یک سندِ حسابداریِ واحد ثبت می‌شوند
(services/treasury.create_treasury_voucher). طبقِ درخواستِ صریح: «دریافت
از آقایِ ایکس مبلغِ ۲۰۰۰ که در فرم مشخص بشه نقدی یا بانک یا چک یا در
قالبِ تخفیف»."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import currencies as currencies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import treasury as treasury_service
from peecha.ui import theme
from peecha.ui.screens.journal_entry import _AmountField, _fill_options, _make_searchable_combo
from peecha.ui.widgets import FieldHelpMixin, JalaliDateEdit

_METHOD_LABELS = {"CASH": "نقدی", "BANK": "بانکی", "CHECK": "چک", "DISCOUNT": "تخفیف"}
_METHOD_CODES = ["CASH", "BANK", "CHECK", "DISCOUNT"]


class _MethodDetailsDialog(QDialog):
    """جزئیاتِ مخصوصِ روشِ انتخاب‌شده‌یِ یک ردیف — نقد/بانک: کدام صندوق/
    حسابِ بانکی؛ چک: شماره/بانک/سررسید/طرف (+دسته‌چک، فقط در پرداخت)."""

    def __init__(self, direction: str, method: str, company_id: int, current: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"جزئیاتِ ردیفِ {_METHOD_LABELS.get(method, method)}")
        layout = QFormLayout(self)

        self.detail_combo: QComboBox | None = None
        self.checkbook_combo: QComboBox | None = None
        self.check_no_field: QLineEdit | None = None
        self.check_bank_field: QLineEdit | None = None
        self.check_due_field: JalaliDateEdit | None = None
        self.check_party_field: QLineEdit | None = None

        if method in ("CASH", "BANK"):
            dimension_code = dimensions_service.CASH_BOX_CODE if method == "CASH" else dimensions_service.BANK_ACCOUNT_CODE
            dimension_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimension_code)
            options = dimensions_service.list_detail_accounts(company_id, dimension_type_id)
            self.detail_combo = QComboBox()
            for option in options:
                self.detail_combo.addItem(option.name or option.code, option.detail_account_id)
            if current.get("detail_account_id") is not None:
                index = self.detail_combo.findData(current["detail_account_id"])
                if index >= 0:
                    self.detail_combo.setCurrentIndex(index)
            layout.addRow("صندوق/تنخواه" if method == "CASH" else "حسابِ بانکی", self.detail_combo)
        elif method == "CHECK":
            if direction == "PAYMENT":
                self.checkbook_combo = QComboBox()
                self.checkbook_combo.addItem("(بدونِ دسته‌چک — شماره‌یِ دستی)", None)
                for checkbook in treasury_service.list_checkbooks(company_id):
                    if checkbook.is_active and checkbook.next_no <= checkbook.end_no:
                        self.checkbook_combo.addItem(
                            f"{checkbook.bank_account_label} "
                            f"({numerals.to_persian_digits(str(checkbook.next_no))}–{numerals.to_persian_digits(str(checkbook.end_no))})",
                            checkbook.checkbook_id,
                        )
                if current.get("checkbook_id") is not None:
                    index = self.checkbook_combo.findData(current["checkbook_id"])
                    if index >= 0:
                        self.checkbook_combo.setCurrentIndex(index)
                layout.addRow("دسته‌چک", self.checkbook_combo)

                bank_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.BANK_ACCOUNT_CODE)
                options = dimensions_service.list_detail_accounts(company_id, bank_type_id)
                self.detail_combo = QComboBox()
                for option in options:
                    self.detail_combo.addItem(option.name or option.code, option.detail_account_id)
                if current.get("detail_account_id") is not None:
                    index = self.detail_combo.findData(current["detail_account_id"])
                    if index >= 0:
                        self.detail_combo.setCurrentIndex(index)
                layout.addRow("حسابِ بانکیِ صادرکننده", self.detail_combo)

            self.check_no_field = QLineEdit(current.get("check_no") or "")
            layout.addRow("شماره‌یِ چک", self.check_no_field)
            self.check_bank_field = QLineEdit(current.get("check_bank_name") or "")
            layout.addRow("بانکِ چک", self.check_bank_field)
            self.check_due_field = JalaliDateEdit("سررسید")
            self.check_due_field.setDate(current.get("check_due_date") or datetime.date.today())
            layout.addRow("سررسید", self.check_due_field)
            self.check_party_field = QLineEdit(current.get("check_party_name") or "")
            layout.addRow("نامِ طرف", self.check_party_field)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def result_data(self) -> dict:
        data: dict = {}
        if self.detail_combo is not None:
            data["detail_account_id"] = self.detail_combo.currentData()
        if self.checkbook_combo is not None:
            data["checkbook_id"] = self.checkbook_combo.currentData()
        if self.check_no_field is not None:
            data["check_no"] = self.check_no_field.text().strip()
        if self.check_bank_field is not None:
            data["check_bank_name"] = self.check_bank_field.text().strip()
        if self.check_due_field is not None:
            data["check_due_date"] = self.check_due_field.date()
        if self.check_party_field is not None:
            data["check_party_name"] = self.check_party_field.text().strip()
        return data


class _MethodRow:
    def __init__(self, screen: "TreasuryVoucherScreen") -> None:
        self._screen = screen
        self.details: dict = {}

        self.method_combo = QComboBox()
        for code in _METHOD_CODES:
            self.method_combo.addItem(_METHOD_LABELS[code], code)

        self.amount_field = _AmountField()
        self.amount_field.setDecimals(screen.currency_decimal_places)

        self.description_field = QLineEdit()

        self.details_button = QPushButton("جزئیات…")
        self.details_button.setObjectName("flatButton")
        self.details_button.clicked.connect(self._open_details)

        self.remove_button = QPushButton("✕")
        self.remove_button.setObjectName("dangerButton")
        self.remove_button.clicked.connect(lambda: screen._remove_row(self))

    def _open_details(self) -> None:
        method = self.method_combo.currentData()
        if method == "DISCOUNT" or self._screen.company_id is None:
            return
        dialog = _MethodDetailsDialog(self._screen.direction, method, self._screen.company_id, self.details, self._screen)
        if dialog.exec() == QDialog.Accepted:
            self.details = dialog.result_data()

    def to_method_line(self) -> treasury_service.MethodLine | None:
        method = self.method_combo.currentData()
        try:
            amount = decimal.Decimal(str(self.amount_field.value()))
        except (ValueError, decimal.InvalidOperation):
            amount = decimal.Decimal(0)
        if amount <= 0:
            return None
        kwargs = {
            "method": method,
            "amount": amount,
            "description": self.description_field.text().strip(),
        }
        if method in ("CASH", "BANK"):
            kwargs["detail_account_id"] = self.details.get("detail_account_id")
        elif method == "CHECK":
            kwargs.update(
                detail_account_id=self.details.get("detail_account_id"),
                check_no=self.details.get("check_no") or "",
                check_bank_name=self.details.get("check_bank_name"),
                check_due_date=self.details.get("check_due_date"),
                check_party_name=self.details.get("check_party_name"),
                checkbook_id=self.details.get("checkbook_id"),
            )
        return treasury_service.MethodLine(**kwargs)


class TreasuryVoucherScreen(FieldHelpMixin, QWidget):
    def __init__(self, direction: str) -> None:
        super().__init__()
        self.direction = direction  # "RECEIPT" یا "PAYMENT"
        self.company_id: int | None = None
        self.currency_decimal_places = 0
        self.account_options: list[tuple[int, str]] = []
        self._detail_combos: dict[int, QComboBox] = {}
        self._method_rows: list[_MethodRow] = []

        noun = "دریافت" if direction == "RECEIPT" else "پرداخت"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        self.title_label = QLabel(f"سندِ {noun}")
        self.title_label.setObjectName("pageTitle")
        layout.addWidget(self.title_label)

        header = QFormLayout()
        self.account_combo = _make_searchable_combo([])
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)
        header.addRow("طرفِ حساب / حسابِ مربوطه", self.account_combo)

        self.date_field = JalaliDateEdit("تاریخِ سند")
        header.addRow("تاریخ", self.date_field)

        self.description_field = QLineEdit()
        header.addRow("شرح", self.description_field)
        layout.addLayout(header)

        self.detail_container = QVBoxLayout()
        detail_widget = QWidget()
        detail_widget.setLayout(self.detail_container)
        layout.addWidget(detail_widget)

        rows_header = QHBoxLayout()
        rows_title = QLabel("ردیف‌هایِ روش")
        rows_title.setObjectName("sectionHint")
        rows_header.addWidget(rows_title)
        rows_header.addStretch(1)
        add_row_button = QPushButton("+ ردیفِ روش")
        add_row_button.setObjectName("flatButton")
        add_row_button.clicked.connect(self._add_row)
        rows_header.addWidget(add_row_button)
        layout.addLayout(rows_header)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["روش", "مبلغ", "شرح", "جزئیات", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

        footer = QHBoxLayout()
        save_button = QPushButton(f"ثبتِ سندِ {noun}")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._save)
        footer.addWidget(save_button)
        footer.addStretch(1)
        layout.addLayout(footer)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.set_field_help([
            (
                self.account_combo,
                "طرفِ حسابی که از او دریافت می‌کنید یا به او پرداخت می‌کنید (مثلاً حسابِ کلِ «حساب‌هایِ دریافتنی»).",
            ),
            (
                self.table,
                "هر ردیف یک روشِ تسویه است (نقدی/بانکی/چک/تخفیف) — می‌توانید یک دریافت را بینِ چند روش تقسیم کنید؛ "
                "جمعِ ردیف‌ها همان مبلغِ کلِ سند می‌شود.",
            ),
        ])

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        self.company_id = self._company_id()
        if self.company_id is None:
            return
        accounts = coa_service.list_postable_accounts(self.company_id)
        self.account_options = [(a.account_id, f"{a.full_code} — {a.name}") for a in accounts]
        _fill_options(self.account_combo, self.account_options)

        base_currency_id = session.current_company.base_currency_id if session.current_company else None
        currency = next((c for c in currencies_service.list_all_currencies() if c.currency_id == base_currency_id), None)
        self.currency_decimal_places = currency.decimal_places if currency else 0

        self._reset_form()

    def _on_account_changed(self, _index: int) -> None:
        while self.detail_container.count():
            child = self.detail_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._detail_combos = {}

        account_id = self.account_combo.currentData()
        if account_id is None or self.company_id is None:
            return
        for required in dimensions_service.get_required_dimensions_for_account(account_id):
            label = "تفصیلیِ اشخاص" if required.code == dimensions_service.PERSON_DIMENSION_CODE else dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(required.code, required.code)
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            combo = _make_searchable_combo([(d.detail_account_id, d.name or d.full_code or d.code) for d in required.detail_accounts])
            row.addWidget(combo, stretch=1)
            wrapper = QWidget()
            wrapper.setLayout(row)
            self.detail_container.addWidget(wrapper)
            self._detail_combos[required.dimension_type_id] = combo

    def _add_row(self) -> None:
        row = _MethodRow(self)
        row_index = self.table.rowCount()
        self.table.insertRow(row_index)
        self.table.setCellWidget(row_index, 0, row.method_combo)
        self.table.setCellWidget(row_index, 1, row.amount_field)
        self.table.setCellWidget(row_index, 2, row.description_field)
        self.table.setCellWidget(row_index, 3, row.details_button)
        self.table.setCellWidget(row_index, 4, row.remove_button)
        self._method_rows.append(row)

    def _remove_row(self, row: _MethodRow) -> None:
        if row not in self._method_rows:
            return
        row_index = self._method_rows.index(row)
        self.table.removeRow(row_index)
        self._method_rows.pop(row_index)

    def _reset_form(self) -> None:
        self.table.setRowCount(0)
        self._method_rows = []
        self._add_row()
        self._add_row()
        self.date_field.setDate(datetime.date.today())
        self.description_field.clear()
        self.account_combo.setCurrentIndex(0)
        self.status_label.setText("")

    def _save(self) -> None:
        if self.company_id is None or session.current_user is None:
            theme.set_status_label(self.status_label, "ابتدا یک شرکت را انتخاب کنید.", ok=False)
            return
        account_id = self.account_combo.currentData()
        if account_id is None:
            theme.set_status_label(self.status_label, "طرفِ حساب / حسابِ مربوطه را انتخاب کنید.", ok=False)
            return
        counterparty_details = {
            dimension_type_id: combo.currentData()
            for dimension_type_id, combo in self._detail_combos.items()
            if combo.currentData() is not None
        }
        method_lines = [ln for row in self._method_rows if (ln := row.to_method_line()) is not None]
        if not method_lines:
            theme.set_status_label(self.status_label, "حداقل یک ردیفِ روش (با مبلغِ مثبت) لازم است.", ok=False)
            return

        try:
            result = treasury_service.create_treasury_voucher(
                self.company_id,
                session.current_user.user_id,
                self.direction,
                account_id,
                counterparty_details,
                self.date_field.date(),
                self.description_field.text().strip(),
                method_lines,
            )
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return

        self._reset_form()
        theme.set_status_label(
            self.status_label,
            f"سند با شماره‌ی موقتِ {numerals.to_persian_digits(str(result.temporary_no))} ثبت شد.",
            ok=True,
        )
