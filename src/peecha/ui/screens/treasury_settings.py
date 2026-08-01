"""تنظیماتِ خزانه‌داری — نگاشتِ ۸اسلاتیِ حساب‌هایِ دریافت/پرداخت +
مدیریتِ دسته‌چک (معادلِ Qt، هم‌الگو با field_labels.py/fiscal_years.py)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import treasury as treasury_service
from peecha.ui.widgets import FieldHelpMixin

_RECEIPT_KEYS = ["RECEIPT_CASH", "RECEIPT_BANK", "RECEIPT_CHECK", "RECEIPT_DISCOUNT"]
_PAYMENT_KEYS = ["PAYMENT_CASH", "PAYMENT_BANK", "PAYMENT_CHECK", "PAYMENT_DISCOUNT"]


class _MappingRow(QWidget):
    def __init__(self, mapping_key: str, label: str, current_account_id: int | None, account_options, on_save) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)

        name_label = QLabel(label)
        name_label.setMinimumWidth(220)
        layout.addWidget(name_label)

        self.account_combo = QComboBox()
        self.account_combo.setEditable(True)
        self.account_combo.setInsertPolicy(QComboBox.NoInsert)
        self.account_combo.addItem("", None)
        for account_id, account_label in account_options:
            self.account_combo.addItem(account_label, account_id)
        completer = QCompleter([label for _v, label in account_options])
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.account_combo.setCompleter(completer)
        if current_account_id is not None:
            index = self.account_combo.findData(current_account_id)
            if index >= 0:
                self.account_combo.setCurrentIndex(index)
        layout.addWidget(self.account_combo, stretch=1)

        save_button = QPushButton("ذخیره")
        save_button.setObjectName("flatButton")
        save_button.clicked.connect(lambda: on_save(mapping_key, self.account_combo.currentData()))
        layout.addWidget(save_button)


class TreasurySettingsScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._mapping_rows: list[_MappingRow] = []

        # هم‌الگو با کارت‌بندیِ فرمِ سندِ حسابداری (journal_entry.py): هر
        # بخشِ منطقی در کارتِ جداگانه، نه یک ستونِ یکدستِ بدونِ مرز.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("تنظیماتِ خزانه‌داری")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

        mapping_card = QWidget()
        mapping_card.setObjectName("card")
        mapping_card_layout = QVBoxLayout(mapping_card)
        mapping_card_layout.setContentsMargins(12, 10, 12, 10)
        mapping_card_layout.setSpacing(4)

        mapping_title = QLabel("نگاشتِ حساب‌هایِ دریافت/پرداخت")
        mapping_title.setObjectName("sectionHint")
        mapping_card_layout.addWidget(mapping_title)

        self.mapping_container = QVBoxLayout()
        self.mapping_container.setSpacing(2)
        mapping_card_layout.addLayout(self.mapping_container)
        layout.addWidget(mapping_card)

        checkbook_card = QWidget()
        checkbook_card.setObjectName("card")
        checkbook_card_layout = QVBoxLayout(checkbook_card)
        checkbook_card_layout.setContentsMargins(12, 10, 12, 10)
        checkbook_card_layout.setSpacing(6)

        checkbook_title = QLabel("دسته‌چک‌ها")
        checkbook_title.setObjectName("sectionHint")
        checkbook_card_layout.addWidget(checkbook_title)

        form_row = QHBoxLayout()
        form_row.addWidget(QLabel("حسابِ بانکی"))
        self.bank_combo = QComboBox()
        form_row.addWidget(self.bank_combo, stretch=1)
        form_row.addWidget(QLabel("از شماره‌ی"))
        self.start_spin = QSpinBox()
        self.start_spin.setRange(1, 999_999_999)
        form_row.addWidget(self.start_spin)
        form_row.addWidget(QLabel("تا شماره‌ی"))
        self.end_spin = QSpinBox()
        self.end_spin.setRange(1, 999_999_999)
        form_row.addWidget(self.end_spin)
        add_checkbook_button = QPushButton("+ دسته‌چکِ جدید")
        add_checkbook_button.setObjectName("flatButton")
        add_checkbook_button.clicked.connect(self._create_checkbook)
        form_row.addWidget(add_checkbook_button)
        checkbook_card_layout.addLayout(form_row)

        self.checkbook_table = QTableWidget(0, 5)
        self.checkbook_table.setHorizontalHeaderLabels(["حسابِ بانکی", "از", "تا", "شماره‌یِ بعدی", "وضعیت"])
        self.checkbook_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.checkbook_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.checkbook_table.verticalHeader().setVisible(False)
        self.checkbook_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.checkbook_table.setMinimumHeight(140)
        self.checkbook_table.cellDoubleClicked.connect(self._toggle_checkbook_row)
        checkbook_card_layout.addWidget(self.checkbook_table, stretch=1)
        layout.addWidget(checkbook_card, stretch=1)

        self.set_field_help([
            (
                self.bank_combo,
                "دسته‌چک به یک حسابِ بانکیِ مشخص تعلق دارد؛ موقعِ صدورِ چکِ پرداختی از فرمِ دریافت/پرداخت، "
                "شماره‌ها به‌ترتیب از همین بازه مصرف می‌شوند.",
            ),
            (self.checkbook_table, "برایِ فعال/غیرفعال‌کردنِ یک دسته‌چک، رویِ ردیفش دابل‌کلیک کنید."),
        ])

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        while self.mapping_container.count():
            child = self.mapping_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._mapping_rows = []
        if company_id is None:
            return

        account_options = [(a.account_id, f"{a.full_code} — {a.name}") for a in coa_service.list_postable_accounts(company_id)]
        mappings_by_key = {m.mapping_key: m.account_id for m in treasury_service.list_account_mappings(company_id)}

        receipt_label = QLabel("دریافت")
        receipt_label.setObjectName("sectionHint")
        self.mapping_container.addWidget(receipt_label)
        for key in _RECEIPT_KEYS:
            row = _MappingRow(key, treasury_service.MAPPING_LABELS[key], mappings_by_key.get(key), account_options, self._save_mapping)
            self.mapping_container.addWidget(row)
            self._mapping_rows.append(row)

        payment_label = QLabel("پرداخت")
        payment_label.setObjectName("sectionHint")
        self.mapping_container.addWidget(payment_label)
        for key in _PAYMENT_KEYS:
            row = _MappingRow(key, treasury_service.MAPPING_LABELS[key], mappings_by_key.get(key), account_options, self._save_mapping)
            self.mapping_container.addWidget(row)
            self._mapping_rows.append(row)

        bank_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.BANK_ACCOUNT_CODE)
        bank_accounts = dimensions_service.list_detail_accounts(company_id, bank_type_id)
        self.bank_combo.clear()
        for account in bank_accounts:
            self.bank_combo.addItem(account.name or account.code, account.detail_account_id)

        self._refresh_checkbooks(company_id)

    def _refresh_checkbooks(self, company_id: int) -> None:
        checkbooks = treasury_service.list_checkbooks(company_id)
        self.checkbook_table.setRowCount(len(checkbooks))
        for row_index, cb in enumerate(checkbooks):
            values = [
                cb.bank_account_label,
                numerals.to_persian_digits(str(cb.start_no)),
                numerals.to_persian_digits(str(cb.end_no)),
                numerals.to_persian_digits(str(cb.next_no)),
                "فعال" if cb.is_active else "غیرفعال",
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, cb.checkbook_id)
                self.checkbook_table.setItem(row_index, col_index, item)

    def _save_mapping(self, mapping_key: str, account_id) -> None:
        company_id = self._company_id()
        if company_id is None or account_id is None:
            self.status_label.setText("ابتدا یک حساب انتخاب کنید.")
            return
        treasury_service.set_account_mapping(company_id, mapping_key, account_id)
        self.status_label.setText("")

    def _create_checkbook(self) -> None:
        company_id = self._company_id()
        bank_detail_id = self.bank_combo.currentData()
        if company_id is None or bank_detail_id is None:
            self.status_label.setText("ابتدا یک حسابِ بانکی انتخاب کنید.")
            return
        try:
            treasury_service.create_checkbook(company_id, bank_detail_id, self.start_spin.value(), self.end_spin.value())
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("")
        self._refresh_checkbooks(company_id)

    def _toggle_checkbook_row(self, row: int, _column: int) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        checkbook_id = self.checkbook_table.item(row, 0).data(Qt.UserRole)
        checkbooks = treasury_service.list_checkbooks(company_id)
        current = next((c for c in checkbooks if c.checkbook_id == checkbook_id), None)
        if current is None:
            return
        confirm = QMessageBox.question(
            self, "تغییرِ وضعیتِ دسته‌چک",
            f"دسته‌چک {'غیرفعال' if current.is_active else 'فعال'} شود؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        treasury_service.set_checkbook_active(checkbook_id, company_id, not current.is_active)
        self._refresh_checkbooks(company_id)
