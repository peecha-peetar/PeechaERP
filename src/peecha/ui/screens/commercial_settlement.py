"""مدیریتِ تسویه‌یِ فاکتورها — طبقِ درخواستِ صریح («هر دریافت و پرداخت
رفرنسِ فاکتور را داشته باشد و مدیریتِ تسویه‌یِ فاکتورها را ایجاد کن»).

چون رسیدِ خزانه‌داری همان سندِ حسابداری (acc.journal_entries، با
entry_type_code یِ RECEIPT/PAYMENT) است، این صفحه یا یک سندِ ازقبل‌ثبت‌شده
را به فاکتورِ انتخاب‌شده وصل می‌کند، یا (طبقِ رفعِ باگِ واقعی: «قبلاً باید
سندِ دریافت/پرداخت از قبل ثبت شده باشد») مستقیماً فرمِ دریافت/پرداخت
(treasury_voucher.py) را با اطلاعاتِ همین فاکتور باز می‌کند -- بعدِ ثبتِ
موفقِ آن سند، خودکار به‌عنوانِ تسویه‌یِ همین فاکتور هم ثبت می‌شود
(treasury_voucher.py:prefill_for_invoice با invoice_document_id)."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
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

from peecha import numerals, session as app_session
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_settlements as settlements_service
from peecha.services import companies as companies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import journal_entries as je_service
from peecha.ui import theme
from peecha.ui.screens.commercial_document import DOC_TYPE_TITLES
from peecha.ui.screens.journal_entry import _AmountField
from peecha.ui.widgets import JalaliDateEdit

_VOUCHER_NAV_CODE_BY_INVOICE_TYPE = {"SALES_INVOICE": "TREASURY_RECEIPT", "PURCHASE_INVOICE": "TREASURY_PAYMENT"}

_INVOICE_COLUMNS = ["نوع", "شماره", "طرفِ‌حساب", "موعدِ تسویه", "جمعِ کل", "تسویه‌شده", "مانده"]
_SETTLEMENT_COLUMNS = ["تاریخ", "مبلغ", "سندِ حسابداری", "شمارهٔ مرجع", "توضیح", "عملیات"]


class InvoiceSettlementScreen(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__()
        self._main_window = main_window
        self._parties_by_id: dict[int, str] = {}
        self._invoice_rows: list[settlements_service.InvoiceSettlementStatus] = []
        self._voucher_entries: list = []
        self._selected_document_id: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)

        title = QLabel("مدیریتِ تسویه‌یِ فاکتورها")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("فقط فاکتورهایِ ثبتِ‌نهایی‌شده که هنوز به‌طورِ کامل تسویه نشده‌اند نمایش داده می‌شوند."))

        self.invoice_table = QTableWidget(0, len(_INVOICE_COLUMNS))
        self.invoice_table.setHorizontalHeaderLabels(_INVOICE_COLUMNS)
        self.invoice_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.invoice_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.invoice_table.verticalHeader().setVisible(False)
        self.invoice_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.invoice_table.itemSelectionChanged.connect(self._on_invoice_selected)
        layout.addWidget(self.invoice_table, stretch=2)

        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("سندِ دریافت/پرداخت"))
        self.voucher_combo = QComboBox()
        self.voucher_combo.setMinimumWidth(260)
        self.voucher_combo.setToolTip(
            "برایِ صدورِ سندِ تازه (پیشنهادی)، همین گزینه را نگه دارید -- با کلیکِ «تسویه»، فرمِ دریافت/پرداخت با "
            "طرفِ‌حساب و مبلغِ همین فاکتور باز می‌شود و بعدِ ثبتِ آن، خودکار به همین فاکتور وصل می‌شود. اگر سندی از "
            "قبل ثبت شده، آن را از این فهرست انتخاب کنید تا فقط رفرنس داده شود."
        )
        add_row.addWidget(self.voucher_combo, stretch=1)
        add_row.addWidget(QLabel("تاریخ"))
        self.settlement_date_field = JalaliDateEdit()
        add_row.addWidget(self.settlement_date_field)
        add_row.addWidget(QLabel("مبلغ"))
        self.amount_field = _AmountField()
        add_row.addWidget(self.amount_field)
        add_row.addWidget(QLabel("شمارهٔ مرجع"))
        self.reference_field = QLineEdit()
        self.reference_field.setMaximumWidth(140)
        add_row.addWidget(self.reference_field)
        self.description_field = QLineEdit()
        self.description_field.setPlaceholderText("توضیح")
        add_row.addWidget(self.description_field, stretch=1)
        add_button = QPushButton("🔗 تسویه")
        add_button.setObjectName("primaryButton")
        add_button.setToolTip(
            "اگر سندِ حسابداری انتخاب نشده باشد، فرمِ دریافت/پرداخت با اطلاعاتِ همین فاکتور باز می‌شود؛ وگرنه فقط "
            "همین سندِ انتخابی به فاکتور رفرنس داده می‌شود."
        )
        add_button.clicked.connect(self._add_settlement)
        add_row.addWidget(add_button)
        layout.addLayout(add_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        layout.addWidget(QLabel("تسویه‌هایِ فاکتورِ انتخاب‌شده"))
        self.settlement_table = QTableWidget(0, len(_SETTLEMENT_COLUMNS))
        self.settlement_table.setHorizontalHeaderLabels(_SETTLEMENT_COLUMNS)
        self.settlement_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.settlement_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.settlement_table.verticalHeader().setVisible(False)
        self.settlement_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        layout.addWidget(self.settlement_table, stretch=1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self.amount_field.setDecimals(companies_service.get_base_currency_decimal_places(company_id))
        self._parties_by_id = {}
        for c in dimensions_service.list_customers(company_id):
            self._parties_by_id[c["detail_account_id"]] = f"{c['code']} — {c['name'] or ''}"
        for s in dimensions_service.list_suppliers(company_id):
            self._parties_by_id[s["detail_account_id"]] = f"{s['code']} — {s['name'] or ''}"

        self._voucher_entries = je_service.list_journal_entries(company_id, entry_type_codes=["RECEIPT", "PAYMENT"])
        self.voucher_combo.clear()
        self.voucher_combo.addItem("🔗 صدورِ سندِ دریافت/پرداختِ تازه (پیشنهادی)", None)
        for entry in self._voucher_entries:
            label = f"#{numerals.to_persian_digits(str(entry.temporary_no))} — {numerals.format_jalali_date(entry.document_date)} — {entry.description or ''}"
            self.voucher_combo.addItem(label, entry.journal_entry_id)

        # طبقِ رفعِ باگِ واقعی (کشف‌شده حینِ افزودنِ بازکردنِ فرمِ دریافت/
        # پرداخت از همین صفحه): انتخابِ فعلی بر اساسِ اندیسِ ردیف در جدول
        # نگه داشته می‌شد -- اگر بعدِ رفرش (مثلاً بعدِ برگشتن از فرمِ
        # دریافت/پرداخت) سندِ قبلاً-انتخاب‌شده جابه‌جا شود یا کلاً از
        # فهرست خارج شود (چون تازه به‌طورِ کامل تسویه شده)، خودِ Qt سیگنالِ
        # تغییرِ انتخاب را شلیک نمی‌کند (چون از دیدِ آن هنوز همان اندیسِ
        # ردیف انتخاب‌شده است) و self._selected_document_id به‌اشتباه رویِ
        # شناسه‌یِ قدیمی می‌ماند -- درحالی‌که آن ردیف حالا سندِ دیگری را
        # نشان می‌دهد. برایِ همین این‌جا صریحاً بر اساسِ شناسه (نه اندیس)
        # دوباره انتخاب/پاک می‌شود.
        previously_selected_document_id = self._selected_document_id
        self._invoice_rows = sorted(
            settlements_service.list_unsettled_invoices(company_id),
            key=lambda r: (r.due_date is None, r.due_date or datetime.date.max),
        )
        self.invoice_table.setRowCount(len(self._invoice_rows))
        today = datetime.date.today()
        for row_index, status in enumerate(self._invoice_rows):
            doc, lines = self._document_lookup(company_id, status.document_id)
            overdue = status.due_date is not None and status.due_date < today
            values = [
                DOC_TYPE_TITLES.get(doc.document_type_code, doc.document_type_code) if doc else "—",
                numerals.to_persian_digits(str(doc.document_no)) if doc else "—",
                self._parties_by_id.get(doc.counterparty_detail_account_id, "—") if doc else "—",
                numerals.format_jalali_date(status.due_date) if status.due_date else "—",
                numerals.format_amount(status.total_amount),
                numerals.format_amount(status.settled_amount),
                numerals.format_amount(status.remaining_amount),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, status.document_id)
                if overdue and col_index == 3:
                    item.setForeground(QColor(theme.DANGER))
                self.invoice_table.setItem(row_index, col_index, item)
        self.invoice_table.resizeRowsToContents()
        match_row = next(
            (row for row in range(self.invoice_table.rowCount())
             if self.invoice_table.item(row, 0).data(Qt.UserRole) == previously_selected_document_id),
            None,
        ) if previously_selected_document_id is not None else None
        if match_row is not None:
            self.invoice_table.selectRow(match_row)
            self._selected_document_id = previously_selected_document_id
        else:
            self.invoice_table.clearSelection()
            self._selected_document_id = None
        self.status_label.setText("")
        self._refresh_settlements_table()

    def _document_lookup(self, company_id: int, document_id: int):
        try:
            return documents_service.get_document(document_id, company_id)
        except ValueError:
            return None, []

    def _on_invoice_selected(self) -> None:
        rows = self.invoice_table.selectionModel().selectedRows()
        if not rows:
            self._selected_document_id = None
        else:
            item = self.invoice_table.item(rows[0].row(), 0)
            self._selected_document_id = item.data(Qt.UserRole)
        self._refresh_settlements_table()

    def _refresh_settlements_table(self) -> None:
        company_id = self._company_id()
        self.settlement_table.setRowCount(0)
        if company_id is None or self._selected_document_id is None:
            return
        settlements = settlements_service.list_settlements_for_invoice(self._selected_document_id, company_id)
        self.settlement_table.setRowCount(len(settlements))
        for row_index, settlement in enumerate(settlements):
            je_label = "—"
            if settlement.journal_entry_id is not None:
                je_label = f"#{numerals.to_persian_digits(str(settlement.journal_entry_id))}"
            values = [
                numerals.format_jalali_date(settlement.settlement_date),
                numerals.format_amount(settlement.amount),
                je_label,
                settlement.reference_no or "—",
                settlement.description or "—",
            ]
            for col_index, value in enumerate(values):
                self.settlement_table.setItem(row_index, col_index, QTableWidgetItem(value))
            remove_button = QPushButton("🗑️")
            remove_button.setObjectName("dangerIconButton")
            remove_button.setToolTip("حذفِ این تسویه")
            remove_button.clicked.connect(lambda _checked=False, sid=settlement.settlement_id: self._remove_settlement(sid))
            self.settlement_table.setCellWidget(row_index, len(_SETTLEMENT_COLUMNS) - 1, remove_button)
        self.settlement_table.resizeRowsToContents()

    def _add_settlement(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        if self._selected_document_id is None:
            self.status_label.setText("ابتدا یک فاکتور را از فهرستِ بالا انتخاب کنید.")
            return
        amount = decimal.Decimal(str(self.amount_field.value()))
        if amount <= 0:
            self.status_label.setText("مبلغِ تسویه باید مثبت باشد.")
            return
        voucher_journal_entry_id = self.voucher_combo.currentData()
        if voucher_journal_entry_id is None:
            # طبقِ رفعِ باگِ واقعی («باید سندِ دریافت/پرداخت از قبل ثبت
            # شده باشد و ما فقط رفرنس بدهیم»): به‌جایِ الزامِ داشتنِ
            # سندِ ازپیش‌ثبت‌شده، همین‌جا فرمِ دریافت/پرداخت با اطلاعاتِ
            # همین فاکتور باز می‌شود؛ بعدِ ثبتِ موفقِ آن سند
            # (treasury_voucher.py:_save)، تسویه خودکار به همین فاکتور
            # وصل می‌شود.
            self._open_voucher_for_settlement(company_id, amount)
            return
        try:
            settlements_service.allocate_settlement(
                company_id, self._selected_document_id, voucher_journal_entry_id,
                self.settlement_date_field.date(), amount, app_session.current_user.user_id,
                reference_no=self.reference_field.text().strip() or None,
                description=self.description_field.text().strip() or None,
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.amount_field.setValue(0)
        self.reference_field.clear()
        self.description_field.clear()
        # طبقِ رفعِ باگِ واقعی: refresh() خودش status_label را برایِ نمایشِ
        # خطاهایِ احتمالیِ فهرست خالی می‌کند -- اگر پیامِ موفقیت پیش از آن
        # گذاشته شود، بلافاصله در سکوت پاک می‌شود.
        self.refresh()
        self.status_label.setObjectName("statusSuccess")
        self.status_label.setText("تسویه ثبت شد.")

    def _open_voucher_for_settlement(self, company_id: int, amount: decimal.Decimal) -> None:
        if self._main_window is None:
            self.status_label.setText("امکانِ بازکردنِ فرمِ دریافت/پرداخت از این‌جا وجود ندارد.")
            return
        doc, _ = self._document_lookup(company_id, self._selected_document_id)
        if doc is None:
            self.status_label.setText("فاکتورِ انتخاب‌شده دیگر معتبر نیست.")
            return
        nav_code = _VOUCHER_NAV_CODE_BY_INVOICE_TYPE.get(doc.document_type_code)
        if nav_code is None:
            self.status_label.setText("این نوعِ سند از طریقِ فرمِ دریافت/پرداخت قابلِ‌تسویه نیست.")
            return
        description = (
            self.description_field.text().strip()
            or f"بابتِ {DOC_TYPE_TITLES.get(doc.document_type_code, doc.document_type_code)}ِ #{numerals.to_persian_digits(str(doc.document_no))}"
        )
        invoice_document_id = self._selected_document_id
        counterparty_id = doc.counterparty_detail_account_id
        self._main_window.open_screen(
            nav_code,
            then=lambda screen: screen.prefill_for_invoice(
                counterparty_id, amount, description, invoice_document_id=invoice_document_id,
            ),
        )

    def _remove_settlement(self, settlement_id: int) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        confirm = QMessageBox.question(self, "حذفِ تسویه", "این تسویه حذف شود؟")
        if confirm != QMessageBox.Yes:
            return
        try:
            settlements_service.remove_settlement(settlement_id, company_id)
        except ValueError as exc:
            self.status_label.setObjectName("statusError")
            self.status_label.setText(str(exc))
            return
        self.refresh()
