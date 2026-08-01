"""تنظیمِ سندِ اتوماتیکِ خزانه‌داری — طبقِ درخواستِ صریح، این فرم زیرِ
تبِ «خزانه‌داری»یِ تنظیماتِ سیستم قرار می‌گیرد (نه یک صفحه‌یِ جداگانه) و
شاملِ سه بخش است: نگاشتِ ۸اسلاتیِ حساب‌هایِ روش (نقد/بانک/چک/تخفیف)،
انواعِ سندِ دریافت/پرداخت (معین + فهرستِ تفصیلی‌هایِ مجازِ طرفِ حساب —
طبقِ درخواستِ صریح: «تفضیلی‌هایِ انتخاب‌شده برایِ معین در نوعِ سند» در
فرمِ سند پیشنهاد/جستجو/انتخاب شوند)، و مدیریتِ دسته‌چک."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
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
from peecha.ui.screens.journal_entry import _fill_options, _make_searchable_combo
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

        self.account_combo = _make_searchable_combo(account_options)
        if current_account_id is not None:
            index = self.account_combo.findData(current_account_id)
            if index >= 0:
                self.account_combo.setCurrentIndex(index)
                self.account_combo.lineEdit().setCursorPosition(0)
        layout.addWidget(self.account_combo, stretch=1)

        save_button = QPushButton("ذخیره")
        save_button.setObjectName("flatButton")
        save_button.clicked.connect(lambda: on_save(mapping_key, self.account_combo.currentData()))
        layout.addWidget(save_button)


class _DocumentTypeForm(QWidget):
    """ردیفِ افزودنِ یک «نوعِ سند» تازه — فقط نام + معین؛ تفصیلی‌هایِ
    مجاز بعداً از رویِ جدولِ زیر (با انتخابِ ردیف) پیوست/حذف می‌شوند."""

    def __init__(self, direction: str, screen: "TreasuryAutoEntrySettingsScreen") -> None:
        super().__init__()
        self._direction = direction
        self._screen = screen

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)

        self.name_field = QLineEdit()
        self.name_field.setPlaceholderText("نامِ نوعِ سند (مثلاً «دریافت از مشتری»)")
        self.name_field.setMinimumWidth(180)
        layout.addWidget(self.name_field, stretch=1)

        self.account_combo = _make_searchable_combo([])
        layout.addWidget(self.account_combo, stretch=1)

        add_button = QPushButton("+ افزودن")
        add_button.setObjectName("flatButton")
        add_button.clicked.connect(self._add)
        layout.addWidget(add_button)

    def set_account_options(self, options: list[tuple[int, str]]) -> None:
        _fill_options(self.account_combo, options)

    def _add(self) -> None:
        company_id = self._screen.company_id
        name = self.name_field.text().strip()
        account_id = self.account_combo.currentData()
        if company_id is None or not name or account_id is None:
            self._screen.set_status("نام و معین را برایِ نوعِ سند مشخص کنید.")
            return
        try:
            treasury_service.create_document_type(company_id, self._direction, name, account_id)
        except ValueError as exc:
            self._screen.set_status(str(exc))
            return
        self._screen.set_status("")
        self.name_field.clear()
        self.account_combo.setCurrentIndex(0)
        self._screen.refresh_document_types(self._direction)


class _DocumentTypeDetailsPanel(QWidget):
    """طبقِ درخواستِ صریح: «تفضیلی‌هایِ انتخاب‌شده برایِ معین در نوعِ سند
    را پیشنهاد و جستجو و انتخاب کنیم» — با انتخابِ یک ردیف از جدولِ
    انواعِ سند، این پنل تفصیلی‌هایِ مجازِ همان نوعِ سند را نشان می‌دهد و
    امکانِ افزودن/حذف می‌دهد (صفرتا = فرمِ سند از بینِ همه می‌پرسد، یک‌تا
    = همیشه خودکار همان، چندتا = فرمِ سند فقط همان‌ها را پیشنهاد می‌دهد)."""

    def __init__(self, direction: str, screen: "TreasuryAutoEntrySettingsScreen") -> None:
        super().__init__()
        self._direction = direction
        self._screen = screen
        self._document_type: treasury_service.DocumentTypeRow | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(4)

        self.title_label = QLabel("برایِ مدیریتِ تفصیلی‌هایِ مجاز، یک نوعِ سند را از جدولِ بالا انتخاب کنید.")
        self.title_label.setObjectName("sectionHint")
        layout.addWidget(self.title_label)

        add_row = QHBoxLayout()
        self.candidate_combo = _make_searchable_combo([])
        self.candidate_combo.setEnabled(False)
        add_row.addWidget(self.candidate_combo, stretch=1)
        self.add_button = QPushButton("+ افزودنِ تفصیلی")
        self.add_button.setObjectName("flatButton")
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self._add_detail)
        add_row.addWidget(self.add_button)
        layout.addLayout(add_row)

        self.attached_table = QTableWidget(0, 1)
        self.attached_table.setHorizontalHeaderLabels(["تفصیلیِ مجاز (برایِ حذف دابل‌کلیک کنید)"])
        self.attached_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.attached_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.attached_table.verticalHeader().setVisible(False)
        self.attached_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.attached_table.setMaximumHeight(110)
        self.attached_table.cellDoubleClicked.connect(self._remove_detail)
        layout.addWidget(self.attached_table)

    def set_document_type(self, document_type: treasury_service.DocumentTypeRow | None) -> None:
        self._document_type = document_type
        self.candidate_combo.setEnabled(False)
        self.add_button.setEnabled(False)
        _fill_options(self.candidate_combo, [])
        self.attached_table.setRowCount(0)

        if document_type is None:
            self.title_label.setText("برایِ مدیریتِ تفصیلی‌هایِ مجاز، یک نوعِ سند را از جدولِ بالا انتخاب کنید.")
            return

        self.title_label.setText(f"تفصیلی‌هایِ مجازِ «{document_type.name}»")
        attached_ids = {detail_account_id for detail_account_id, _label in document_type.detail_options}
        self.attached_table.setRowCount(len(document_type.detail_options))
        for row_index, (detail_account_id, label) in enumerate(document_type.detail_options):
            item = QTableWidgetItem(label)
            item.setData(Qt.UserRole, detail_account_id)
            self.attached_table.setItem(row_index, 0, item)

        required = dimensions_service.get_required_dimensions_for_account(document_type.account_id)
        if len(required) != 1:
            return
        candidates = [
            (d.detail_account_id, d.name or d.full_code or d.code)
            for d in required[0].detail_accounts
            if d.detail_account_id not in attached_ids
        ]
        _fill_options(self.candidate_combo, candidates)
        self.candidate_combo.setEnabled(True)
        self.add_button.setEnabled(True)

    def _add_detail(self) -> None:
        company_id = self._screen.company_id
        detail_account_id = self.candidate_combo.currentData()
        if self._document_type is None or company_id is None or detail_account_id is None:
            self._screen.set_status("یک تفصیلی برایِ افزودن انتخاب کنید.")
            return
        treasury_service.add_document_type_detail(self._document_type.document_type_id, company_id, detail_account_id)
        self._screen.set_status("")
        self._screen.refresh_document_types(self._direction, reselect_document_type_id=self._document_type.document_type_id)

    def _remove_detail(self, row: int, _column: int) -> None:
        company_id = self._screen.company_id
        if self._document_type is None or company_id is None:
            return
        detail_account_id = self.attached_table.item(row, 0).data(Qt.UserRole)
        treasury_service.remove_document_type_detail(self._document_type.document_type_id, company_id, detail_account_id)
        self._screen.refresh_document_types(self._direction, reselect_document_type_id=self._document_type.document_type_id)


class TreasuryAutoEntrySettingsScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.company_id: int | None = None
        self._mapping_rows: list[_MappingRow] = []
        self._document_type_tables: dict[str, QTableWidget] = {}
        self._document_type_forms: dict[str, _DocumentTypeForm] = {}
        self._document_type_detail_panels: dict[str, _DocumentTypeDetailsPanel] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("تنظیمِ سندِ اتوماتیک")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

        # --- انواعِ سند (دریافت/پرداخت) --------------------------------------
        for direction, section_title, hint in (
            ("RECEIPT", "انواعِ سندِ دریافت", "طرفِ بستانکارِ سندِ دریافت — مثلاً «دریافت از مشتری» -> حساب‌هایِ دریافتنی."),
            ("PAYMENT", "انواعِ سندِ پرداخت", "طرفِ بدهکارِ سندِ پرداخت — مثلاً «پرداخت به تامین‌کننده» -> حساب‌هایِ پرداختنی."),
        ):
            card = QWidget()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(6)

            card_title = QLabel(section_title)
            card_title.setObjectName("sectionHint")
            card_layout.addWidget(card_title)

            form = _DocumentTypeForm(direction, self)
            card_layout.addWidget(form)
            self._document_type_forms[direction] = form

            table = QTableWidget(0, 3)
            table.setHorizontalHeaderLabels(["نام", "معین", "تفصیلی‌هایِ مجاز"])
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            table.setMinimumHeight(120)
            table.cellDoubleClicked.connect(lambda row, _col, d=direction: self._delete_document_type(d, row))
            table.itemSelectionChanged.connect(lambda d=direction: self._on_document_type_row_selected(d))
            card_layout.addWidget(table, stretch=1)
            self._document_type_tables[direction] = table

            details_panel = _DocumentTypeDetailsPanel(direction, self)
            card_layout.addWidget(details_panel)
            self._document_type_detail_panels[direction] = details_panel

            layout.addWidget(card)
            self.set_field_help([(form, hint)])

        # --- نگاشتِ حساب‌هایِ روش ---------------------------------------------
        mapping_card = QWidget()
        mapping_card.setObjectName("card")
        mapping_card_layout = QVBoxLayout(mapping_card)
        mapping_card_layout.setContentsMargins(12, 10, 12, 10)
        mapping_card_layout.setSpacing(4)

        mapping_title = QLabel("نگاشتِ حساب‌هایِ روش (نقد/بانک/چک/تخفیف)")
        mapping_title.setObjectName("sectionHint")
        mapping_card_layout.addWidget(mapping_title)

        self.mapping_container = QVBoxLayout()
        self.mapping_container.setSpacing(2)
        mapping_card_layout.addLayout(self.mapping_container)
        layout.addWidget(mapping_card)

        # --- دسته‌چک‌ها ---------------------------------------------------------
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
            (self._document_type_tables["RECEIPT"], "برایِ حذفِ یک نوعِ سند، رویِ ردیفش دابل‌کلیک کنید."),
        ])

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        self.company_id = self._company_id()
        while self.mapping_container.count():
            child = self.mapping_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._mapping_rows = []
        if self.company_id is None:
            return
        company_id = self.company_id

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

        for direction, form in self._document_type_forms.items():
            form.set_account_options(account_options)
            self.refresh_document_types(direction)

        bank_type_id = dimensions_service.get_specialized_dimension_type_id(company_id, dimensions_service.BANK_ACCOUNT_CODE)
        bank_accounts = dimensions_service.list_detail_accounts(company_id, bank_type_id)
        self.bank_combo.clear()
        for account in bank_accounts:
            self.bank_combo.addItem(account.name or account.code, account.detail_account_id)

        self._refresh_checkbooks(company_id)

    def refresh_document_types(self, direction: str, reselect_document_type_id: int | None = None) -> None:
        if self.company_id is None:
            return
        table = self._document_type_tables[direction]
        rows = treasury_service.list_document_types(self.company_id, direction)
        table.blockSignals(True)
        table.setRowCount(len(rows))
        reselect_row = -1
        for row_index, r in enumerate(rows):
            detail_summary = "، ".join(label for _id, label in r.detail_options) if r.detail_options else "(در فرمِ سند پرسیده می‌شود)"
            values = [r.name, r.account_label, detail_summary]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, r.document_type_id)
                table.setItem(row_index, col_index, item)
            if r.document_type_id == reselect_document_type_id:
                reselect_row = row_index
        table.blockSignals(False)

        panel = self._document_type_detail_panels[direction]
        if reselect_row >= 0:
            table.selectRow(reselect_row)
            panel.set_document_type(rows[reselect_row])
        else:
            table.clearSelection()
            panel.set_document_type(None)

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
            self.set_status("ابتدا یک حساب انتخاب کنید.")
            return
        treasury_service.set_account_mapping(company_id, mapping_key, account_id)
        self.set_status("")

    def _on_document_type_row_selected(self, direction: str) -> None:
        if self.company_id is None:
            return
        table = self._document_type_tables[direction]
        selected_rows = table.selectionModel().selectedRows() if table.selectionModel() else []
        panel = self._document_type_detail_panels[direction]
        if not selected_rows:
            panel.set_document_type(None)
            return
        document_type_id = table.item(selected_rows[0].row(), 0).data(Qt.UserRole)
        row = next(
            (r for r in treasury_service.list_document_types(self.company_id, direction) if r.document_type_id == document_type_id),
            None,
        )
        panel.set_document_type(row)

    def _delete_document_type(self, direction: str, row: int) -> None:
        if self.company_id is None:
            return
        table = self._document_type_tables[direction]
        document_type_id = table.item(row, 0).data(Qt.UserRole)
        confirm = QMessageBox.question(
            self, "حذفِ نوعِ سند", "این نوعِ سند حذف شود؟", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        treasury_service.delete_document_type(document_type_id, self.company_id)
        self.refresh_document_types(direction)

    def _create_checkbook(self) -> None:
        company_id = self._company_id()
        bank_detail_id = self.bank_combo.currentData()
        if company_id is None or bank_detail_id is None:
            self.set_status("ابتدا یک حسابِ بانکی انتخاب کنید.")
            return
        try:
            treasury_service.create_checkbook(company_id, bank_detail_id, self.start_spin.value(), self.end_spin.value())
        except ValueError as exc:
            self.set_status(str(exc))
            return
        self.set_status("")
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
