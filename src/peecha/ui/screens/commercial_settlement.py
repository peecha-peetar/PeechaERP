"""مدیریتِ تسویه‌یِ فاکتورها — طبقِ درخواستِ صریح («هر دریافت و پرداخت
رفرنسِ فاکتور را داشته باشد و مدیریتِ تسویه‌یِ فاکتورها را ایجاد کن»).

طبقِ درخواستِ صریحِ کاربر (دورِ بعدی):
۱) فرمِ فروش و خرید کاملاً جدا -- همین کلاس با پارامترِ invoice_type دوبار
   نمونه‌سازی می‌شود (commercial_invoice_settlement_sales/_purchase).
۲) تسویه‌یِ چند فاکتورِ هم‌زمان با یک سندِ دریافت/پرداختِ واحد -- هر ردیفِ
   جدول فیلدِ «مبلغِ تسویه»یِ خودش را دارد؛ دکمه‌یِ «تسویه» همه‌یِ
   ردیف‌هایِ دارایِ مبلغ را هم‌زمان می‌بَرد.
۳) فیلترهایِ طرفِ‌حساب/کالا/تاریخِ سند/وضعیتِ سررسید.
۴) بنرِ هشدارِ موعدِ تسویه (تنظیماتش در commercial_settings.py، ولی تا
   پیش‌ازاین هیچ صفحه‌ای list_invoices_due_soon را صدا نمی‌زد -- این‌جا
   اولین مصرف‌کننده‌یِ واقعی‌اش است).
۵) زنجیره‌یِ Enter -- هم رویِ فیلترها، هم رویِ ستونِ مبلغِ هر ردیف (ردیف‌به‌ردیف
   تا دکمه‌یِ تسویه)، هم رویِ ردیفِ عملیات.

چون رسیدِ خزانه‌داری همان سندِ حسابداری (acc.journal_entries، با
entry_type_code یِ RECEIPT/PAYMENT) است، این صفحه یا یک سندِ ازقبل‌ثبت‌شده
را به فاکتورهایِ انتخاب‌شده وصل می‌کند، یا (طبقِ رفعِ باگِ واقعی: «قبلاً
باید سندِ دریافت/پرداخت از قبل ثبت شده باشد») مستقیماً فرمِ دریافت/پرداخت
(treasury_voucher.py) را با اطلاعاتِ همان فاکتور(ها) باز می‌کند -- بعدِ
ثبتِ موفقِ آن سند، خودکار به‌عنوانِ تسویه‌یِ همه‌شان هم ثبت می‌شود
(treasury_voucher.py:prefill_for_invoice با settle_invoices)."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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
from peecha.services import inventory_catalog as catalog_service
from peecha.services import journal_entries as je_service
from peecha.ui import theme
from peecha.ui.screens.treasury_voucher import _describe_invoice_settlement
from peecha.ui.screens.inventory_document import _enter_signal
from peecha.ui.screens.journal_entry import _AmountField, _fill_options, _make_searchable_combo
from peecha.ui.screens.treasury_voucher import _EnterComboBox
from peecha.ui.widgets import JalaliDateEdit

_VOUCHER_NAV_CODE_BY_INVOICE_TYPE = {"SALES_INVOICE": "TREASURY_RECEIPT", "PURCHASE_INVOICE": "TREASURY_PAYMENT"}
_INVOICE_EDIT_NAV_CODE_BY_TYPE = {"SALES_INVOICE": "SALES_INVOICE", "PURCHASE_INVOICE": "PURCH_INVOICE"}
_VOUCHER_ENTRY_TYPE_BY_INVOICE_TYPE = {"SALES_INVOICE": ["RECEIPT"], "PURCHASE_INVOICE": ["PAYMENT"]}
_DUE_STATUS_FILTER_OPTIONS = [("(همه)", None), ("معوقه", "OVERDUE"), ("نزدیکِ سررسید", "DUE_SOON")]

_INVOICE_COLUMNS = ["شماره", "طرفِ‌حساب", "موعدِ تسویه", "جمعِ کل", "تسویه‌شده", "مانده", "مبلغِ تسویه"]
_SETTLEMENT_COLUMNS = ["تاریخ", "مبلغ", "سندِ حسابداری", "شمارهٔ مرجع", "توضیح", "عملیات"]


class InvoiceSettlementScreen(QWidget):
    def __init__(self, main_window, invoice_type: str) -> None:
        super().__init__()
        self._main_window = main_window
        self._invoice_type = invoice_type
        self._is_sales = invoice_type == "SALES_INVOICE"
        self._parties_by_id: dict[int, str] = {}
        self._decimal_places = 0
        self._all_statuses: list[settlements_service.InvoiceSettlementStatus] = []
        self._doc_cache: dict[int, tuple] = {}
        self._invoice_rows: list[settlements_service.InvoiceSettlementStatus] = []
        self._voucher_entries: list = []
        self._selected_document_id: int | None = None
        self._amount_fields: dict[int, _AmountField] = {}
        self._alarm_settings = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)

        title = QLabel("تسویه‌یِ فاکتورهایِ فروش" if self._is_sales else "تسویه‌یِ فاکتورهایِ خرید")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("فقط فاکتورهایِ ثبتِ‌نهایی‌شده که هنوز به‌طورِ کامل تسویه نشده‌اند نمایش داده می‌شوند."))

        # --- فیلترها: طبقِ درخواستِ صریح («فیلترها و جستجوی فاکتور بر
        # اساسِ شخص و کالا و تاریخ»). ---
        filters_row = QHBoxLayout()
        filters_row.addWidget(QLabel("مشتری" if self._is_sales else "تامین‌کننده"))
        self.counterparty_filter_combo = _make_searchable_combo([])
        self.counterparty_filter_combo.setMinimumWidth(170)
        self.counterparty_filter_combo.lineEdit().setPlaceholderText("(همه)")
        filters_row.addWidget(self.counterparty_filter_combo)

        filters_row.addWidget(QLabel("کالا"))
        self.item_filter_combo = _make_searchable_combo([])
        self.item_filter_combo.setMinimumWidth(170)
        self.item_filter_combo.lineEdit().setPlaceholderText("(همه)")
        filters_row.addWidget(self.item_filter_combo)

        self.date_filter_checkbox = QCheckBox("فیلترِ تاریخِ سند")
        filters_row.addWidget(self.date_filter_checkbox)
        filters_row.addWidget(QLabel("از"))
        self.date_from_field = JalaliDateEdit()
        filters_row.addWidget(self.date_from_field)
        filters_row.addWidget(QLabel("تا"))
        self.date_to_field = JalaliDateEdit()
        filters_row.addWidget(self.date_to_field)

        filters_row.addWidget(QLabel("سررسید"))
        self.due_status_filter_combo = _EnterComboBox()
        for label, code in _DUE_STATUS_FILTER_OPTIONS:
            self.due_status_filter_combo.addItem(label, code)
        filters_row.addWidget(self.due_status_filter_combo)

        clear_filters_button = QPushButton("✕")
        clear_filters_button.setObjectName("iconButton")
        clear_filters_button.setFixedWidth(36)
        clear_filters_button.setToolTip("پاک‌کردنِ فیلترها")
        clear_filters_button.clicked.connect(self._clear_filters)
        filters_row.addWidget(clear_filters_button)
        filters_row.addStretch(1)
        layout.addLayout(filters_row)

        self.date_from_field.setEnabled(False)
        self.date_to_field.setEnabled(False)
        self.date_filter_checkbox.toggled.connect(self._on_date_filter_toggled)
        self.counterparty_filter_combo.currentIndexChanged.connect(self._apply_filters)
        self.item_filter_combo.currentIndexChanged.connect(self._apply_filters)
        self.due_status_filter_combo.currentIndexChanged.connect(self._apply_filters)
        # طبقِ رفعِ باگِ واقعی: تغییرِ خودِ تاریخ‌هایِ از/تا (برخلافِ تیکِ
        # فعال‌سازیِ فیلتر) هیچ رویدادی به _apply_filters نمی‌فرستاد --
        # کاربر تاریخ را عوض می‌کرد ولی جدول تا تعاملِ دیگری (مثلاً
        # فیلترِ دیگر) به‌روز نمی‌شد.
        self.date_from_field.editingFinished.connect(self._apply_filters)
        self.date_to_field.editingFinished.connect(self._apply_filters)

        filter_chain = [
            self.counterparty_filter_combo, self.item_filter_combo,
            self.date_from_field, self.date_to_field, self.due_status_filter_combo,
        ]
        for widget, next_widget in zip(filter_chain, filter_chain[1:]):
            _enter_signal(widget).connect(next_widget.setFocus)

        self.invoice_table = QTableWidget(0, len(_INVOICE_COLUMNS))
        self.invoice_table.setHorizontalHeaderLabels(_INVOICE_COLUMNS)
        self.invoice_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.invoice_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.invoice_table.verticalHeader().setVisible(False)
        # طبقِ رفعِ باگِ واقعی («عرضِ ستونِ طرفِ‌حساب زیاد و مبلغِ تسویه کمه
        # و تناسب نداره» + گزارشِ بعدی «اندازه‌یِ ستون‌ها نامتقارن است»):
        # ResizeToContents هر ستون را جدا و بر اساسِ طولِ عددِ همان ستون
        # اندازه می‌کند -- مثلاً «تسویه‌شده» با مقدارِ ۰ خیلی باریک‌تر از
        # «جمعِ کل» با یک عددِ بزرگ می‌شود، درحالی‌که هر دو از یک جنس‌اند
        # (مبلغ) و باید یک‌اندازه دیده شوند. حالا هر گروهِ هم‌جنس (سه
        # ستونِ مبلغ، شماره، تاریخ) عرضِ ثابت و برابرِ صریح دارد -- نه
        # اندازه‌یِ خودکارِ وابسته به محتوایِ همان لحظه -- و فقط طرفِ‌حساب/
        # مبلغِ تسویه (که به‌طورِ ذاتی متغیرترند) قابلِ‌تغییرِ دستی یا
        # کِش‌دارند.
        invoice_header = self.invoice_table.horizontalHeader()
        invoice_header.setSectionResizeMode(0, QHeaderView.Interactive)
        self.invoice_table.setColumnWidth(0, 70)
        invoice_header.setSectionResizeMode(1, QHeaderView.Interactive)
        self.invoice_table.setColumnWidth(1, 200)
        invoice_header.setSectionResizeMode(2, QHeaderView.Interactive)
        self.invoice_table.setColumnWidth(2, 100)
        for col in (3, 4, 5):
            invoice_header.setSectionResizeMode(col, QHeaderView.Interactive)
            self.invoice_table.setColumnWidth(col, 110)
        invoice_header.setSectionResizeMode(len(_INVOICE_COLUMNS) - 1, QHeaderView.Stretch)
        self.invoice_table.itemSelectionChanged.connect(self._on_invoice_selected)
        # طبقِ درخواستِ صریح («روی ردیفِ فاکتور بتوان فاکتور را کامل دید»):
        # دابل‌کلیک رویِ هر ردیف، همان فاکتورِ واقعی را در فرمِ خودش
        # (فقط‌مشاهده اگر ثبتِ‌نهایی شده باشد) باز می‌کند -- هم‌الگو با
        # commercial_documents_list.py.
        self.invoice_table.setToolTip("برایِ مشاهده‌یِ کاملِ فاکتور، رویِ ردیف دوبار کلیک کنید.")
        self.invoice_table.cellDoubleClicked.connect(self._open_invoice_document)
        layout.addWidget(self.invoice_table, stretch=2)

        # --- طبقِ درخواستِ صریح («مبلغِ دریافتی برایِ چند فاکتور هم وارد
        # کند») -- ردیفِ اقدام: سندِ حسابداری/تاریخ/مرجع/توضیح مشترکِ کلِ
        # عملیات‌اند؛ مبلغِ هر فاکتور در خودِ جدولِ بالا (ستونِ آخر) است. ---
        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("سندِ دریافت/پرداخت"))
        self.voucher_combo = _EnterComboBox()
        self.voucher_combo.setMinimumWidth(260)
        self.voucher_combo.setToolTip(
            "برایِ صدورِ سندِ تازه (پیشنهادی)، همین گزینه را نگه دارید -- با کلیکِ «تسویه»، فرمِ دریافت/پرداخت با "
            "طرفِ‌حساب و مجموعِ مبلغ‌هایِ واردشده باز می‌شود و بعدِ ثبتِ آن، خودکار به همان فاکتورها وصل می‌شود. اگر "
            "سندی از قبل ثبت شده، آن را از این فهرست انتخاب کنید تا فقط رفرنس داده شود."
        )
        add_row.addWidget(self.voucher_combo, stretch=1)
        add_row.addWidget(QLabel("تاریخ"))
        self.settlement_date_field = JalaliDateEdit()
        add_row.addWidget(self.settlement_date_field)
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
            "همه‌یِ ردیف‌هایِ جدولِ بالا که برایشان مبلغ وارد شده، هم‌زمان تسویه می‌شوند. اگر سندِ حسابداری انتخاب "
            "نشده باشد، فرمِ دریافت/پرداخت با اطلاعاتِ همان فاکتور(ها) باز می‌شود؛ وگرنه فقط همین سندِ انتخابی "
            "رفرنس داده می‌شود."
        )
        add_button.clicked.connect(self._add_settlement)
        add_row.addWidget(add_button)
        layout.addLayout(add_row)

        action_chain = [self.voucher_combo, self.settlement_date_field, self.reference_field, self.description_field]
        for widget, next_widget in zip(action_chain, action_chain[1:]):
            _enter_signal(widget).connect(next_widget.setFocus)
        _enter_signal(self.description_field).connect(self._add_settlement)

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

    def _on_date_filter_toggled(self, checked: bool) -> None:
        self.date_from_field.setEnabled(checked)
        self.date_to_field.setEnabled(checked)
        self._apply_filters()

    def _clear_filters(self) -> None:
        self.counterparty_filter_combo.setCurrentIndex(0)
        self.item_filter_combo.setCurrentIndex(0)
        self.date_filter_checkbox.setChecked(False)
        self.due_status_filter_combo.setCurrentIndex(0)
        self._apply_filters()

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._decimal_places = companies_service.get_base_currency_decimal_places(company_id)

        if self._is_sales:
            counterparty_options = [(c["detail_account_id"], f"{c['code']} — {c['name'] or ''}") for c in dimensions_service.list_customers(company_id)]
        else:
            counterparty_options = [(c["detail_account_id"], f"{c['code']} — {c['name'] or ''}") for c in dimensions_service.list_suppliers(company_id)]
        self._parties_by_id = dict(counterparty_options)
        current_counterparty = self.counterparty_filter_combo.currentData()
        _fill_options(self.counterparty_filter_combo, counterparty_options)
        if current_counterparty is not None:
            index = self.counterparty_filter_combo.findData(current_counterparty)
            if index >= 0:
                self.counterparty_filter_combo.setCurrentIndex(index)

        item_options = [(it.item_id, f"{it.code} — {it.name or ''}") for it in catalog_service.list_items(company_id)]
        current_item = self.item_filter_combo.currentData()
        _fill_options(self.item_filter_combo, item_options)
        if current_item is not None:
            index = self.item_filter_combo.findData(current_item)
            if index >= 0:
                self.item_filter_combo.setCurrentIndex(index)

        current_voucher = self.voucher_combo.currentData()
        self._voucher_entries = je_service.list_journal_entries(
            company_id, entry_type_codes=_VOUCHER_ENTRY_TYPE_BY_INVOICE_TYPE[self._invoice_type],
        )
        self.voucher_combo.clear()
        self.voucher_combo.addItem("🔗 صدورِ سندِ دریافت/پرداختِ تازه (پیشنهادی)", None)
        for entry in self._voucher_entries:
            label = f"#{numerals.to_persian_digits(str(entry.temporary_no))} — {numerals.format_jalali_date(entry.document_date)} — {entry.description or ''}"
            self.voucher_combo.addItem(label, entry.journal_entry_id)
        if current_voucher is not None:
            index = self.voucher_combo.findData(current_voucher)
            if index >= 0:
                self.voucher_combo.setCurrentIndex(index)

        # طبقِ درخواستِ صریح («آلارم در فرمِ تسویه فایده نداره»): بنرِ
        # هشدار از این فرم برداشته شد و به داشبوردِ اصلیِ برنامه منتقل شد
        # (dashboard.py) -- کاربر بدونِ بازکردنِ این فرمِ خاص هم مطلع
        # می‌شود. این‌جا فقط تنظیماتش برایِ فیلترِ «نزدیکِ سررسید» پایین‌تر
        # لازم است.
        self._alarm_settings = settlements_service.get_alarm_settings(company_id)
        self._all_statuses = settlements_service.list_unsettled_invoices(company_id, self._invoice_type)
        self._doc_cache = {status.document_id: self._document_lookup(company_id, status.document_id) for status in self._all_statuses}
        self._apply_filters()
        self.status_label.setText("")

    def _document_lookup(self, company_id: int, document_id: int):
        try:
            return documents_service.get_document(document_id, company_id)
        except ValueError:
            return None, []

    def _apply_filters(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        # طبقِ رفعِ باگِ واقعی (کشف‌شده حینِ افزودنِ بازکردنِ فرمِ دریافت/
        # پرداخت از همین صفحه): انتخابِ فعلی بر اساسِ اندیسِ ردیف در جدول
        # نگه داشته می‌شد -- بعدِ بازسازیِ جدول (رفرش/فیلتر)، اگر آن سند
        # جابه‌جا/حذف می‌شد، انتخاب به‌اشتباه رویِ سندِ دیگری در همان ردیف
        # می‌ماند. حالا انتخاب بر اساسِ شناسه (نه اندیس) دوباره حل می‌شود.
        previously_selected_document_id = self._selected_document_id

        counterparty_filter = self.counterparty_filter_combo.currentData()
        item_filter = self.item_filter_combo.currentData()
        due_status_filter = self.due_status_filter_combo.currentData()
        use_date_filter = self.date_filter_checkbox.isChecked()
        date_from = self.date_from_field.date() if use_date_filter else None
        date_to = self.date_to_field.date() if use_date_filter else None

        today = datetime.date.today()
        alarm_days = self._alarm_settings.alarm_days_before if self._alarm_settings else 2
        due_soon_threshold = today + datetime.timedelta(days=max(alarm_days, 0))

        filtered = []
        for status in self._all_statuses:
            doc, lines = self._doc_cache.get(status.document_id, (None, []))
            if doc is None:
                continue
            if counterparty_filter is not None and doc.counterparty_detail_account_id != counterparty_filter:
                continue
            if item_filter is not None and not any(ln.item_id == item_filter for ln in lines):
                continue
            if use_date_filter and not (date_from <= doc.document_date <= date_to):
                continue
            if due_status_filter == "OVERDUE" and not (status.due_date is not None and status.due_date < today):
                continue
            if due_status_filter == "DUE_SOON" and not (
                status.due_date is not None and today <= status.due_date <= due_soon_threshold
            ):
                continue
            filtered.append(status)

        self._invoice_rows = sorted(filtered, key=lambda r: (r.due_date is None, r.due_date or datetime.date.max))
        self._amount_fields = {}
        self.invoice_table.setRowCount(len(self._invoice_rows))
        for row_index, status in enumerate(self._invoice_rows):
            doc, _lines = self._doc_cache.get(status.document_id, (None, []))
            overdue = status.due_date is not None and status.due_date < today
            due_soon = not overdue and status.due_date is not None and status.due_date <= due_soon_threshold
            values = [
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
                if col_index == 2 and overdue:
                    item.setForeground(QColor(theme.DANGER))
                elif col_index == 2 and due_soon:
                    item.setForeground(QColor(theme.WARNING))
                self.invoice_table.setItem(row_index, col_index, item)
            amount_field = _AmountField()
            amount_field.setDecimals(self._decimal_places)
            amount_field.setValue(0)
            self._amount_fields[status.document_id] = amount_field
            self.invoice_table.setCellWidget(row_index, len(_INVOICE_COLUMNS) - 1, amount_field)
        self.invoice_table.resizeRowsToContents()
        self._wire_amount_field_enter_chain()

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
        self._refresh_settlements_table()

    def _wire_amount_field_enter_chain(self) -> None:
        # طبقِ درخواستِ صریح («پیمایش با دکمه‌یِ اینتر»): از مبلغِ هر
        # فاکتور به مبلغِ فاکتورِ بعدی، و از آخرین ردیف مستقیم به عملیاتِ
        # تسویه -- مثلِ ورودِ سریعِ اطلاعات در یک صفحه‌گسترده.
        fields = [self._amount_fields[status.document_id] for status in self._invoice_rows]
        for field, next_field in zip(fields, fields[1:]):
            _enter_signal(field).connect(next_field.setFocus)
        if fields:
            _enter_signal(fields[-1]).connect(self._add_settlement)

    def _on_invoice_selected(self) -> None:
        rows = self.invoice_table.selectionModel().selectedRows()
        if not rows:
            self._selected_document_id = None
        else:
            item = self.invoice_table.item(rows[0].row(), 0)
            self._selected_document_id = item.data(Qt.UserRole)
        self._refresh_settlements_table()

    def _open_invoice_document(self, row: int, _column: int) -> None:
        if self._main_window is None:
            return
        item = self.invoice_table.item(row, 0)
        if item is None:
            return
        document_id = item.data(Qt.UserRole)
        nav_code = _INVOICE_EDIT_NAV_CODE_BY_TYPE[self._invoice_type]
        self._main_window.open_screen(nav_code, then=lambda screen: screen.edit_document(document_id))

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

    def _collect_settlement_entries(self) -> list[tuple[int, decimal.Decimal]]:
        entries = []
        for document_id, field in self._amount_fields.items():
            amount = decimal.Decimal(str(field.value()))
            if amount > 0:
                entries.append((document_id, amount))
        return entries

    def _add_settlement(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        entries = self._collect_settlement_entries()
        if not entries:
            self.status_label.setObjectName("statusError")
            self.status_label.setText("برایِ حداقل یک فاکتور، ستونِ «مبلغِ تسویه» را پر کنید.")
            return
        voucher_journal_entry_id = self.voucher_combo.currentData()
        if voucher_journal_entry_id is None:
            # طبقِ رفعِ باگِ واقعی («باید سندِ دریافت/پرداخت از قبل ثبت
            # شده باشد و ما فقط رفرنس بدهیم»): به‌جایِ الزامِ داشتنِ
            # سندِ ازپیش‌ثبت‌شده، همین‌جا فرمِ دریافت/پرداخت با اطلاعاتِ
            # همین فاکتور(ها) باز می‌شود؛ بعدِ ثبتِ موفقِ آن سند
            # (treasury_voucher.py:_save)، تسویه خودکار به همین
            # فاکتورها وصل می‌شود.
            self._open_voucher_for_settlement(company_id, entries)
            return

        succeeded = 0
        errors: list[str] = []
        for document_id, amount in entries:
            try:
                settlements_service.allocate_settlement(
                    company_id, document_id, voucher_journal_entry_id,
                    self.settlement_date_field.date(), amount, app_session.current_user.user_id,
                    reference_no=self.reference_field.text().strip() or None,
                    description=self.description_field.text().strip() or None,
                )
                succeeded += 1
            except ValueError as exc:
                errors.append(f"#{numerals.to_persian_digits(str(document_id))}: {exc}")

        self.reference_field.clear()
        self.description_field.clear()
        # طبقِ رفعِ باگِ واقعی: refresh() خودش status_label را برایِ نمایشِ
        # خطاهایِ احتمالیِ فهرست خالی می‌کند -- اگر پیامِ موفقیت پیش از آن
        # گذاشته شود، بلافاصله در سکوت پاک می‌شود.
        self.refresh()
        if errors:
            self.status_label.setObjectName("statusError")
            prefix = f"{numerals.to_persian_digits(str(succeeded))} تسویه ثبت شد؛ " if succeeded else ""
            self.status_label.setText(prefix + "خطا برایِ برخی: " + " ؛ ".join(errors))
        else:
            self.status_label.setObjectName("statusSuccess")
            self.status_label.setText(
                "تسویه ثبت شد." if succeeded == 1 else f"تسویه‌یِ هر {numerals.to_persian_digits(str(succeeded))} فاکتور ثبت شد."
            )

    def _open_voucher_for_settlement(self, company_id: int, entries: list[tuple[int, decimal.Decimal]]) -> None:
        if self._main_window is None:
            self.status_label.setObjectName("statusError")
            self.status_label.setText("امکانِ بازکردنِ فرمِ دریافت/پرداخت از این‌جا وجود ندارد.")
            return
        docs = []
        for document_id, _amount in entries:
            doc, _lines = self._document_lookup(company_id, document_id)
            if doc is None:
                self.status_label.setObjectName("statusError")
                self.status_label.setText("یکی از فاکتورهایِ انتخاب‌شده دیگر معتبر نیست.")
                return
            docs.append(doc)
        counterparties = {d.counterparty_detail_account_id for d in docs}
        if len(counterparties) > 1:
            self.status_label.setObjectName("statusError")
            self.status_label.setText(
                "برایِ صدورِ یک سندِ دریافت/پرداختِ واحد، فقط فاکتورهایِ یک طرفِ‌حساب را هم‌زمان تسویه کنید."
            )
            return
        nav_code = _VOUCHER_NAV_CODE_BY_INVOICE_TYPE[self._invoice_type]
        total_amount = sum((amount for _doc_id, amount in entries), decimal.Decimal(0))
        counterparty_id = next(iter(counterparties))
        manual_description = self.description_field.text().strip()
        if manual_description:
            description = manual_description
        else:
            # طبقِ درخواستِ صریح («وقتی مقدارِ تسویه برایِ یک فاکتورِ خاص
            # وارد می‌شود، شرحِ پیش‌فرضِ هدر را سیستم ایجاد کند»): همان
            # قالبِ استفاده‌شده در treasury_voucher.py، برایِ یکدستی.
            direction = "RECEIPT" if self._is_sales else "PAYMENT"
            entries_info = [
                (doc.document_no, settlements_service.get_invoice_settlement_status(doc.document_id, company_id).remaining_amount, amount)
                for (doc_id, amount), doc in zip(entries, docs)
            ]
            counterparty_label = self._parties_by_id.get(counterparty_id, "")
            description = _describe_invoice_settlement(direction, entries_info, counterparty_label)
        self._main_window.open_screen(
            nav_code,
            then=lambda screen: screen.prefill_for_invoice(
                counterparty_id, total_amount, description, settle_invoices=entries,
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
