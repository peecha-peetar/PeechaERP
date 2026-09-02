"""مدیریتِ اقساط -- طبقِ درخواستِ صریح («روشِ دریافت/پرداختِ اقساطی»):
فهرستِ همه‌یِ اقساطِ برنامه‌ریزی‌شده (از طریقِ روشِ «اقساط» در فرمِ
دریافت/پرداخت) با وضعیتِ هرکدام. طبقِ درخواستِ بعدی («وصولِ اقساط بتونه
مستقل هم کار بکنه»)، دکمه‌یِ «وصول» در همین صفحه مستقیماً فرمِ دریافت/
پرداخت را با طرفِ‌حساب/مبلغِ همان قسط باز می‌کند -- دیگر نیازی به رفتنِ
دستی به treasury_voucher.py و جستجویِ قسط از دکمه‌یِ 🔗 نیست (آن راه هم
هم‌چنان کار می‌کند). وصول می‌تواند جزئی هم باشد -- مانده و مبلغِ
وصول‌شده‌یِ هر قسط جداگانه نمایش داده می‌شود."""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session as app_session
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import installments as installments_service
from peecha.ui import theme
from peecha.ui.screens.commercial_document import DOC_TYPE_TITLES
from peecha.ui.screens.journal_entry import _fill_options, _make_searchable_combo
from peecha.ui.widgets import JalaliDateEdit

_STATUS_LABELS = {"PENDING": "درانتظار", "OVERDUE": "معوقه", "PAID": "دریافت/پرداخت‌شده"}
_COLUMNS = ["نوع", "شماره‌یِ فاکتور", "طرفِ‌حساب", "قسط", "سررسید", "مبلغِ کل", "وصول‌شده", "مانده", "وضعیت", "وصول"]


class InstallmentsListScreen(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__()
        self._main_window = main_window

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)

        title = QLabel("مدیریتِ اقساط")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("با کلیکِ «وصول» رویِ هر ردیف، فرمِ دریافت/پرداخت با طرفِ‌حساب و ماندهٔ همان قسط باز می‌شود -- وصولِ جزئی هم ممکن است."))

        # --- فیلترها: طبقِ درخواستِ صریح («بالای فرم افرادی که اقساط
        # دارند فیلتر و بر اساسِ تاریخ و طرفِ‌حساب بشه فیلتر کرد»). ---
        filters = QHBoxLayout()
        filters.addWidget(QLabel("وضعیت"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("(همه)", None)
        for code, label in _STATUS_LABELS.items():
            self.status_filter.addItem(label, code)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.status_filter)

        filters.addWidget(QLabel("طرفِ‌حساب"))
        self.counterparty_filter_combo = _make_searchable_combo([])
        self.counterparty_filter_combo.setMinimumWidth(180)
        self.counterparty_filter_combo.lineEdit().setPlaceholderText("(همه)")
        self.counterparty_filter_combo.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.counterparty_filter_combo)

        self.date_filter_checkbox = QCheckBox("فیلترِ سررسید")
        self.date_filter_checkbox.toggled.connect(self._on_date_filter_toggled)
        filters.addWidget(self.date_filter_checkbox)
        filters.addWidget(QLabel("از"))
        self.date_from_field = JalaliDateEdit()
        self.date_from_field.setEnabled(False)
        self.date_from_field.editingFinished.connect(self.refresh)
        filters.addWidget(self.date_from_field)
        filters.addWidget(QLabel("تا"))
        self.date_to_field = JalaliDateEdit()
        self.date_to_field.setEnabled(False)
        self.date_to_field.editingFinished.connect(self.refresh)
        filters.addWidget(self.date_to_field)

        clear_filters_button = QPushButton("✕")
        clear_filters_button.setObjectName("iconButton")
        clear_filters_button.setFixedWidth(36)
        clear_filters_button.setToolTip("پاک‌کردنِ فیلترها")
        clear_filters_button.clicked.connect(self._clear_filters)
        filters.addWidget(clear_filters_button)
        filters.addStretch(1)
        layout.addLayout(filters)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def _on_date_filter_toggled(self, checked: bool) -> None:
        self.date_from_field.setEnabled(checked)
        self.date_to_field.setEnabled(checked)
        self.refresh()

    def _clear_filters(self) -> None:
        self.status_filter.setCurrentIndex(0)
        self.counterparty_filter_combo.setCurrentIndex(0)
        self.date_filter_checkbox.setChecked(False)
        self.refresh()

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return

        # طبقِ باگِ کشف‌شده (RecursionError): counterparty_filter_combo به
        # self.refresh وصل است -- بدونِ blockSignals، هر clear()/addItem()ِ
        # داخلِ _fill_options دوباره currentIndexChanged را امیت می‌کرد و
        # خودِ refresh را از نو صدا می‌زد (بازگشتِ نامتناهی).
        counterparty_options = [
            (c["detail_account_id"], f"{c['code']} — {c['name'] or ''}") for c in dimensions_service.list_customers(company_id)
        ] + [
            (s["detail_account_id"], f"{s['code']} — {s['name'] or ''}") for s in dimensions_service.list_suppliers(company_id)
        ]
        current_counterparty = self.counterparty_filter_combo.currentData()
        self.counterparty_filter_combo.blockSignals(True)
        _fill_options(self.counterparty_filter_combo, counterparty_options)
        if current_counterparty is not None:
            index = self.counterparty_filter_combo.findData(current_counterparty)
            if index >= 0:
                self.counterparty_filter_combo.setCurrentIndex(index)
        self.counterparty_filter_combo.blockSignals(False)

        status_code = self.status_filter.currentData()
        counterparty_filter = self.counterparty_filter_combo.currentData()
        due_date_from = self.date_from_field.date() if self.date_filter_checkbox.isChecked() else None
        due_date_to = self.date_to_field.date() if self.date_filter_checkbox.isChecked() else None
        rows = installments_service.list_installments(
            company_id, status_codes=[status_code] if status_code else None,
            counterparty_detail_account_id=counterparty_filter,
            due_date_from=due_date_from, due_date_to=due_date_to,
        )
        self.table.setRowCount(len(rows))
        today = datetime.date.today()
        for row_index, line in enumerate(rows):
            overdue = line.status_code == "OVERDUE" or (line.status_code == "PENDING" and line.due_date < today)
            status_label = _STATUS_LABELS.get(line.status_code, line.status_code)
            if line.status_code != "PAID" and line.collected_amount > 0:
                status_label = f"{status_label} (وصولِ جزئی)"
            values = [
                DOC_TYPE_TITLES.get(line.document_type_code, line.document_type_code) if line.document_type_code else "—",
                numerals.to_persian_digits(str(line.document_no)) if line.document_no else "—",
                line.counterparty_label or "—",
                numerals.to_persian_digits(str(line.installment_no)),
                numerals.format_jalali_date(line.due_date),
                numerals.format_company_amount(line.amount),
                numerals.format_company_amount(line.collected_amount),
                numerals.format_company_amount(line.remaining_amount),
                status_label,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if overdue and col_index in (4, 7):
                    item.setForeground(QColor(theme.DANGER))
                self.table.setItem(row_index, col_index, item)

            collect_button = QPushButton("💰 وصول")
            collect_button.setEnabled(line.status_code != "PAID" and line.direction in ("RECEIPT", "PAYMENT"))
            collect_button.setToolTip(
                "بازکردنِ فرمِ دریافت/پرداخت با طرفِ‌حساب و ماندهٔ همین قسط -- وصولِ جزئی (کمتر از مانده) هم ممکن است."
                if line.direction in ("RECEIPT", "PAYMENT")
                else "جهتِ این قسط (دریافت/پرداخت) مشخص نیست."
            )
            collect_button.clicked.connect(lambda _checked=False, line=line: self._collect(line))
            self.table.setCellWidget(row_index, 9, collect_button)
        self.table.resizeRowsToContents()

    def _collect(self, line: installments_service.InstallmentLineRow) -> None:
        if line.direction not in ("RECEIPT", "PAYMENT"):
            return
        nav_code = "TREASURY_RECEIPT" if line.direction == "RECEIPT" else "TREASURY_PAYMENT"
        doc_part = f"فاکتورِ #{numerals.to_persian_digits(str(line.document_no))} — " if line.document_no else ""
        description = f"{doc_part}وصولِ قسطِ #{numerals.to_persian_digits(str(line.installment_no))}"
        self._main_window.open_screen(
            nav_code,
            then=lambda screen: screen.prefill_for_installment_collection(
                line.line_id, line.counterparty_detail_account_id, line.remaining_amount, description,
            ),
        )
