"""فرمِ واقعیِ «تنخواه‌گردان» — طبقِ گزارشِ صریح:
  ۱) طرفِ‌حساب (تنخواه‌دار) باید تفصیلیِ سطحِ آخرِ گروهِ «تنخواه» باشد.
  ۲) هر تنخواه‌دار می‌تواند هم‌زمان چند تنخواهِ باز داشته باشد؛ هرکدام با
     شماره‌یِ خودکارِ مستقلِ خودش (per custodian).
  ۳) افتتاحِ تنخواه یک سندِ پرداختِ واقعیِ اولیه لازم دارد (واریزی به
     تنخواه‌دار) — همان روش‌هایِ پرداختِ ازپیش‌تعریف‌شده.
  ۴) ردیف‌هایی که در دورانِ بازبودنِ تنخواه ثبت می‌شوند هیچ سندِ
     حسابداری‌ای نمی‌سازند (نه حتی پیش‌نویس)؛ فقط وقتی تنخواه‌دار خودش
     تنخواه را می‌بندد، یک سندِ موقتِ پیش‌نویس ساخته می‌شود که او را به‌
     اندازه‌یِ جمعِ ردیف‌ها بستانکار می‌کند."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals
from peecha import session
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import petty_cash as petty_cash_service
from peecha.services import treasury as treasury_service
from peecha.ui import theme
from peecha.ui.screens.journal_entry import _fill_options, _make_searchable_combo
from peecha.ui.widgets import FieldHelpMixin, FormScreenBase, JalaliDateEdit

_METHOD_LABELS = {"CASH": "نقد", "BANK": "بانک", "CHECK": "چک"}
_NEW_FUND_SENTINEL = "__NEW__"


class PettyCashScreen(FieldHelpMixin, FormScreenBase):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.company_id: int | None = None
        self._current_fund_id: int | None = None
        self._lines: list[petty_cash_service.PettyCashFundLineRow] = []
        self._opening_rows: list[tuple[QWidget, QComboBox, QDoubleSpinBox, QLineEdit]] = []

        layout = self.body_layout
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(8)

        title = QLabel("تنخواه‌گردان")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        # --- تنخواه‌دار + انتخابِ تنخواه ------------------------------------
        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("تنخواه‌دار (تفصیلیِ سطحِ آخرِ گروهِ تنخواه)"))
        self.custodian_combo = _make_searchable_combo([])
        self.custodian_combo.currentIndexChanged.connect(self._on_custodian_changed)
        picker_row.addWidget(self.custodian_combo, stretch=1)
        picker_row.addWidget(QLabel("تنخواه"))
        self.fund_combo = QComboBox()
        self.fund_combo.currentIndexChanged.connect(self._on_fund_changed)
        picker_row.addWidget(self.fund_combo, stretch=1)
        layout.addLayout(picker_row)

        self.fund_no_label = QLabel("")
        self.fund_no_label.setObjectName("sectionHint")
        layout.addWidget(self.fund_no_label)

        # --- بخشِ افتتاحِ تنخواهِ تازه ---------------------------------------
        self.open_section = QWidget()
        open_layout = QVBoxLayout(self.open_section)
        open_layout.setContentsMargins(0, 0, 0, 0)
        open_layout.setSpacing(6)

        open_date_row = QHBoxLayout()
        open_date_row.addWidget(QLabel("تاریخِ افتتاح"))
        self.opening_date_field = JalaliDateEdit()
        open_date_row.addWidget(self.opening_date_field)
        open_layout.addLayout(open_date_row)

        desc_row = QHBoxLayout()
        desc_row.addWidget(QLabel("شرح"))
        self.opening_description_field = QLineEdit()
        desc_row.addWidget(self.opening_description_field, stretch=1)
        open_layout.addLayout(desc_row)

        open_layout.addWidget(QLabel("واریزیِ اولیه (روشِ پرداخت)"))
        self.opening_rows_container = QVBoxLayout()
        open_layout.addLayout(self.opening_rows_container)

        add_opening_row_button = QPushButton("+ ردیفِ واریزی")
        add_opening_row_button.setObjectName("flatButton")
        add_opening_row_button.clicked.connect(self._add_opening_row)
        open_layout.addWidget(add_opening_row_button)

        self.open_fund_button = QPushButton("افتتاحِ تنخواه")
        self.open_fund_button.setObjectName("primaryButton")
        self.open_fund_button.clicked.connect(self._open_fund)
        open_layout.addWidget(self.open_fund_button)

        layout.addWidget(self.open_section)

        # --- بخشِ مدیریتِ ردیف‌هایِ یک تنخواهِ بازِ‌موجود ---------------------
        self.manage_section = QWidget()
        manage_layout = QVBoxLayout(self.manage_section)
        manage_layout.setContentsMargins(0, 0, 0, 0)
        manage_layout.setSpacing(6)

        self.lines_table = QTableWidget(0, 4)
        self.lines_table.setHorizontalHeaderLabels(["روش", "مبلغ", "شرح", ""])
        self.lines_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lines_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        manage_layout.addWidget(self.lines_table)

        self.lines_total_label = QLabel("")
        self.lines_total_label.setObjectName("sectionHint")
        manage_layout.addWidget(self.lines_total_label)

        add_line_row = QHBoxLayout()
        self.line_method_combo = QComboBox()
        for code, label in _METHOD_LABELS.items():
            self.line_method_combo.addItem(label, code)
        self.line_method_combo.currentIndexChanged.connect(self._on_line_method_changed)
        add_line_row.addWidget(self.line_method_combo)
        self.line_amount_field = QDoubleSpinBox()
        self.line_amount_field.setRange(0, 10_000_000_000)
        self.line_amount_field.setDecimals(0)
        add_line_row.addWidget(self.line_amount_field)
        self.line_description_field = QLineEdit()
        self.line_description_field.setPlaceholderText("شرح")
        add_line_row.addWidget(self.line_description_field, stretch=1)
        self.line_detail_combo = _make_searchable_combo([])
        self.line_detail_combo.setVisible(False)
        add_line_row.addWidget(self.line_detail_combo)
        self.line_check_no_field = QLineEdit()
        self.line_check_no_field.setPlaceholderText("شماره‌یِ چک")
        self.line_check_no_field.setVisible(False)
        add_line_row.addWidget(self.line_check_no_field)
        self.line_check_due_field = JalaliDateEdit()
        self.line_check_due_field.setVisible(False)
        add_line_row.addWidget(self.line_check_due_field)
        add_line_button = QPushButton("افزودنِ ردیف")
        add_line_button.clicked.connect(self._add_line)
        add_line_row.addWidget(add_line_button)
        manage_layout.addLayout(add_line_row)

        self.close_fund_button = QPushButton("بستنِ تنخواه")
        self.close_fund_button.setObjectName("dangerButton")
        self.close_fund_button.clicked.connect(self._close_fund)
        manage_layout.addWidget(self.close_fund_button)

        layout.addWidget(self.manage_section)
        layout.addStretch(1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        self.footer_layout.addWidget(self.status_label, stretch=1)

        self._on_line_method_changed()

    # --- بارگذاری ----------------------------------------------------------
    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        self.company_id = self._company_id()
        if self.company_id is None:
            return
        custodians = petty_cash_service.list_custodians(self.company_id)
        custodian_options = [
            (c.detail_account_id, f"{c.full_code} — {c.name}" if c.name else c.full_code) for c in custodians
        ]
        _fill_options(self.custodian_combo, custodian_options)

        bank_dim_type_id = dimensions_service.get_specialized_dimension_type_id(self.company_id, dimensions_service.BANK_ACCOUNT_CODE)
        bank_details = dimensions_service.list_leaf_detail_accounts(self.company_id, bank_dim_type_id)
        bank_options = [
            (b.detail_account_id, f"{b.full_code} — {b.name}" if b.name else b.full_code) for b in bank_details
        ]
        _fill_options(self.line_detail_combo, bank_options)

        self._reset_opening_rows()
        self._on_custodian_changed()

    def _reset_form(self) -> None:
        self.refresh()

    def _on_custodian_changed(self) -> None:
        custodian_id = self.custodian_combo.currentData()
        self.fund_combo.clear()
        self.fund_combo.addItem("+ تنخواهِ تازه", _NEW_FUND_SENTINEL)
        if custodian_id is not None and self.company_id is not None:
            for fund in petty_cash_service.list_funds(self.company_id, custodian_id):
                status_word = "باز" if fund.status == "OPEN" else "بسته"
                self.fund_combo.addItem(f"شماره‌یِ {numerals.to_persian_digits(str(fund.fund_no))} ({status_word})", fund.fund_id)
        self.fund_combo.setCurrentIndex(0)
        self._on_fund_changed()

    def _on_fund_changed(self) -> None:
        data = self.fund_combo.currentData()
        if data == _NEW_FUND_SENTINEL or data is None:
            self._current_fund_id = None
            self.open_section.setVisible(True)
            self.manage_section.setVisible(False)
            self.fund_no_label.setText("")
            return
        fund = petty_cash_service.get_fund(data)
        if fund is None:
            return
        self._current_fund_id = fund.fund_id
        self.open_section.setVisible(False)
        self.manage_section.setVisible(True)
        status_word = "باز" if fund.status == "OPEN" else "بسته"
        self.fund_no_label.setText(
            f"تنخواهِ شماره‌یِ {numerals.to_persian_digits(str(fund.fund_no))} — وضعیت: {status_word} — "
            f"مبلغِ افتتاح: {numerals.format_money(fund.opening_amount, 0)}"
        )
        self.close_fund_button.setEnabled(fund.status == "OPEN")
        self.line_method_combo.setEnabled(fund.status == "OPEN")
        self._refresh_lines()

    # --- ردیف‌هایِ افتتاحِ تنخواهِ تازه ------------------------------------
    def _reset_opening_rows(self) -> None:
        while self.opening_rows_container.count():
            item = self.opening_rows_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._opening_rows = []
        self._add_opening_row()

    def _add_opening_row(self) -> None:
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        method_combo = QComboBox()
        method_combo.addItem("نقد", "CASH")
        method_combo.addItem("بانک", "BANK")
        row_layout.addWidget(method_combo)
        amount_field = QDoubleSpinBox()
        amount_field.setRange(0, 10_000_000_000)
        amount_field.setDecimals(0)
        row_layout.addWidget(amount_field)
        description_field = QLineEdit()
        description_field.setPlaceholderText("شرح")
        row_layout.addWidget(description_field, 1)
        self.opening_rows_container.addWidget(row_widget)
        self._opening_rows.append((row_widget, method_combo, amount_field, description_field))

    def _open_fund(self) -> None:
        if self.company_id is None or session.current_user is None:
            return
        custodian_id = self.custodian_combo.currentData()
        if custodian_id is None:
            theme.set_status_label(self.status_label, "تنخواه‌دار را انتخاب کنید.", ok=False)
            return
        method_lines = [
            treasury_service.MethodLine(method=method_combo.currentData(), amount=decimal.Decimal(str(amount_field.value())), description=description_field.text().strip())
            for _widget, method_combo, amount_field, description_field in self._opening_rows
            if amount_field.value() > 0
        ]
        if not method_lines:
            theme.set_status_label(self.status_label, "حداقل یک ردیفِ واریزیِ اولیه (با مبلغِ مثبت) لازم است.", ok=False)
            return
        try:
            fund_id, _result = petty_cash_service.open_fund(
                self.company_id, session.current_user.user_id, custodian_id,
                self.opening_date_field.date(), self.opening_description_field.text().strip(), method_lines,
            )
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return
        theme.set_status_label(self.status_label, "تنخواه با موفقیت افتتاح شد.", ok=True)
        self._on_custodian_changed()
        index = self.fund_combo.findData(fund_id)
        if index >= 0:
            self.fund_combo.setCurrentIndex(index)

    # --- ردیف‌هایِ یک تنخواهِ بازِ‌موجود ------------------------------------
    def _on_line_method_changed(self) -> None:
        method = self.line_method_combo.currentData()
        self.line_detail_combo.setVisible(method == "BANK")
        self.line_check_no_field.setVisible(method == "CHECK")
        self.line_check_due_field.setVisible(method == "CHECK")

    def _refresh_lines(self) -> None:
        if self._current_fund_id is None:
            self._lines = []
        else:
            self._lines = petty_cash_service.list_lines(self._current_fund_id)
        self.lines_table.setRowCount(len(self._lines))
        for row_index, line in enumerate(self._lines):
            values = [_METHOD_LABELS.get(line.method, line.method), numerals.format_amount(line.amount), line.description or ""]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, line.line_id)
                self.lines_table.setItem(row_index, col_index, item)
            delete_button = QPushButton("🗑️")
            delete_button.setObjectName("dangerIconButton")
            delete_button.setFixedWidth(34)
            delete_button.setToolTip("حذف")
            delete_button.clicked.connect(lambda _checked=False, line_id=line.line_id: self._delete_line(line_id))
            delete_button.setEnabled(self.close_fund_button.isEnabled())
            self.lines_table.setCellWidget(row_index, 3, delete_button)
        total = sum((l.amount for l in self._lines), decimal.Decimal(0))
        self.lines_total_label.setText(f"جمعِ ردیف‌ها: {numerals.format_money(total, 0)}")

    def _add_line(self) -> None:
        if self._current_fund_id is None:
            return
        method = self.line_method_combo.currentData()
        amount = decimal.Decimal(str(self.line_amount_field.value()))
        if amount <= 0:
            theme.set_status_label(self.status_label, "مبلغِ ردیف را وارد کنید.", ok=False)
            return
        try:
            petty_cash_service.add_line(
                self._current_fund_id, method, amount, self.line_description_field.text().strip(),
                detail_account_id=self.line_detail_combo.currentData() if method == "BANK" else None,
                check_no=self.line_check_no_field.text().strip() or None if method == "CHECK" else None,
                check_due_date=self.line_check_due_field.date() if method == "CHECK" else None,
            )
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return
        self.line_amount_field.setValue(0)
        self.line_description_field.clear()
        self.line_check_no_field.clear()
        theme.set_status_label(self.status_label, "ردیف ثبت شد.", ok=True)
        self._refresh_lines()

    def _delete_line(self, line_id: int) -> None:
        confirm = QMessageBox.question(self, "حذفِ ردیف", "این ردیف حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            petty_cash_service.delete_line(line_id)
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return
        self._refresh_lines()

    def _close_fund(self) -> None:
        if self._current_fund_id is None or session.current_user is None:
            return
        if not self._lines:
            theme.set_status_label(self.status_label, "برایِ بستنِ تنخواه حداقل یک ردیف لازم است.", ok=False)
            return
        confirm = QMessageBox.question(
            self, "بستنِ تنخواه",
            "با بستنِ تنخواه، سندِ موقتِ پیش‌نویسِ تسویه ساخته می‌شود و دیگر امکانِ افزودنِ ردیفِ تازه نیست. ادامه می‌دهید؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            result = petty_cash_service.close_fund(self._current_fund_id, session.current_user.user_id, datetime.date.today())
        except ValueError as exc:
            theme.set_status_label(self.status_label, str(exc), ok=False)
            return
        theme.set_status_label(
            self.status_label,
            f"تنخواه بسته شد؛ سندِ موقتِ پیش‌نویس با شماره‌ی موقتِ {numerals.to_persian_digits(str(result.temporary_no))} ساخته شد.",
            ok=True,
        )
        self._on_custodian_changed()
