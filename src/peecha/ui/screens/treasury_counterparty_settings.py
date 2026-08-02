"""تعریفِ انواعِ سندِ دریافت/پرداخت — طبقِ درخواستِ صریح: در هر ردیف یک
«نوعِ تفصیلی» (مثلاً «مشتری») انتخاب می‌شود و در ستونِ بعدی معینِ حسابِ
مربوطه — سمتِ بستانکار برایِ دریافت، سمتِ بدهکار برایِ پرداخت."""

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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import treasury as treasury_service
from peecha.ui.screens.journal_entry import _fill_options, _make_searchable_combo
from peecha.ui.widgets import FieldHelpMixin


class _MappingForm(QWidget):
    """ردیفِ افزودنِ یک نگاشتِ تازه: نوعِ تفصیلی + معین."""

    def __init__(self, direction: str, screen: "TreasuryCounterpartySettingsScreen") -> None:
        super().__init__()
        self._direction = direction
        self._screen = screen

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)

        self.group_combo = QComboBox()
        layout.addWidget(self.group_combo, stretch=1)

        self.account_combo = _make_searchable_combo([])
        layout.addWidget(self.account_combo, stretch=1)

        add_button = QPushButton("+ افزودن")
        add_button.setObjectName("flatButton")
        add_button.clicked.connect(self._add)
        layout.addWidget(add_button)

    def set_options(self, group_options: list[tuple[tuple[str, int], str]], account_options: list[tuple[int, str]]) -> None:
        self.group_combo.clear()
        self.group_combo.addItem("— انتخابِ نوعِ تفصیلی —", None)
        for data, label in group_options:
            self.group_combo.addItem(label, data)
        _fill_options(self.account_combo, account_options)

    def _add(self) -> None:
        company_id = self._screen.company_id
        group_data = self.group_combo.currentData()
        account_id = self.account_combo.currentData()
        if company_id is None or group_data is None or account_id is None:
            self._screen.set_status("نوعِ تفصیلی و معین را انتخاب کنید.")
            return
        kind, key = group_data
        try:
            treasury_service.create_counterparty_mapping(
                company_id,
                self._direction,
                account_id,
                person_group_id=key if kind == "person" else None,
                dimension_type_id=key if kind == "dim" else None,
            )
        except ValueError as exc:
            self._screen.set_status(str(exc))
            return
        self._screen.set_status("")
        self.group_combo.setCurrentIndex(0)
        self.account_combo.setCurrentIndex(0)
        self._screen.refresh_mappings(self._direction)


class _MethodMappingRow(QWidget):
    """ردیفِ نگاشتِ معینِ یک روشِ ردیفِ پایینِ سندِ دریافت (نقد/چک/تخفیف) —
    طبقِ درخواستِ صریح: طرفِ بدهکارِ همین ردیف‌ها، در تنظیماتِ سند."""

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


class _TemplateRow(QWidget):
    """ردیفِ ویرایشِ قالبِ متنِ خودکارِ شرحِ یک روش — طبقِ درخواستِ صریح
    («دستِ کاربر باشه که چه متنی اعمال بشه»)."""

    def __init__(self, template_key: str, label: str, current_text: str, on_save) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)

        name_label = QLabel(label)
        name_label.setMinimumWidth(120)
        layout.addWidget(name_label)

        self.text_field = QLineEdit(current_text)
        layout.addWidget(self.text_field, stretch=1)

        save_button = QPushButton("ذخیره")
        save_button.setObjectName("flatButton")
        save_button.clicked.connect(lambda: on_save(template_key, self.text_field.text()))
        layout.addWidget(save_button)


_RECEIPT_METHOD_KEYS = [
    "RECEIPT_CASH",
    "RECEIPT_BANK",
    "RECEIPT_CHECK",
    "RECEIPT_DISCOUNT",
    "RECEIPT_GOODS_COUPON",
    "RECEIPT_VOUCHER",
    "RECEIPT_NETTING",
]
_PAYMENT_METHOD_KEYS = [
    "PAYMENT_CASH",
    "PAYMENT_BANK",
    "PAYMENT_CHECK",
    "PAYMENT_DISCOUNT",
    "PAYMENT_CHECK_DISBURSEMENT",
    "PAYMENT_NETTING",
]
_METHOD_KEYS_BY_DIRECTION = {"RECEIPT": _RECEIPT_METHOD_KEYS, "PAYMENT": _PAYMENT_METHOD_KEYS}


class TreasuryCounterpartySettingsScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.company_id: int | None = None
        self._forms: dict[str, _MappingForm] = {}
        self._tables: dict[str, QTableWidget] = {}
        self._method_mapping_containers: dict[str, QVBoxLayout] = {}
        self._method_mapping_rows: dict[str, list[_MethodMappingRow]] = {"RECEIPT": [], "PAYMENT": []}
        self._template_rows: list[_TemplateRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("انواعِ سندِ دریافت/پرداخت")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

        help_fields: list[tuple[QWidget, str]] = []
        for direction, section_title, account_col_title, hint in (
            (
                "RECEIPT",
                "انواعِ سندِ دریافت",
                "معینِ حسابِ بستانکار",
                "برایِ هر نوعِ تفصیلی (مثلاً «مشتری»)، معینِ حسابی که سمتِ بستانکارِ سندِ دریافت می‌شود را مشخص کنید.",
            ),
            (
                "PAYMENT",
                "انواعِ سندِ پرداخت",
                "معینِ حسابِ بدهکار",
                "برایِ هر نوعِ تفصیلی (مثلاً «تامین‌کننده»)، معینِ حسابی که سمتِ بدهکارِ سندِ پرداخت می‌شود را مشخص کنید.",
            ),
        ):
            card = QWidget()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(6)

            card_title = QLabel(section_title)
            card_title.setObjectName("sectionHint")
            card_layout.addWidget(card_title)

            form = _MappingForm(direction, self)
            card_layout.addWidget(form)
            self._forms[direction] = form

            table = QTableWidget(0, 2)
            table.setHorizontalHeaderLabels(["نوعِ تفصیلی", account_col_title])
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            table.setMinimumHeight(140)
            table.cellDoubleClicked.connect(lambda row, _col, d=direction: self._delete_mapping(d, row))
            card_layout.addWidget(table, stretch=1)
            self._tables[direction] = table

            layout.addWidget(card, stretch=1)
            help_fields.append((form, hint))
            help_fields.append((table, "برایِ حذفِ یک ردیف، رویِ آن دابل‌کلیک کنید."))

        # --- روش‌هایِ ردیفِ پایینِ سندِ دریافت/پرداخت ---------------------------
        # طبقِ درخواستِ صریح: طرفِ بستانکارِ ردیف‌هایِ دریافت (نقد/بانک/چک/
        # تخفیف/تهاتر) و طرفِ بدهکارِ ردیف‌هایِ پرداخت (همان‌ها + پرداخت با
        # چکِ دریافتی) هم این‌جا تعریف شوند.
        for direction, method_card_title, method_hint in (
            (
                "RECEIPT",
                "روش‌هایِ ردیفِ پایینِ سندِ دریافت (نقد/بانک/چک/تخفیف/کالابرگ/بن/تهاتر)",
                "معینِ سمتِ بستانکارِ ردیف‌هایِ روشِ سندِ دریافت.",
            ),
            (
                "PAYMENT",
                "روش‌هایِ ردیفِ پایینِ سندِ پرداخت (نقد/بانک/چک/تخفیف/خرجِ چک/تهاتر)",
                "معینِ سمتِ بدهکارِ ردیف‌هایِ روشِ سندِ پرداخت.",
            ),
        ):
            method_card = QWidget()
            method_card.setObjectName("card")
            method_card_layout = QVBoxLayout(method_card)
            method_card_layout.setContentsMargins(12, 10, 12, 10)
            method_card_layout.setSpacing(4)

            method_title = QLabel(method_card_title)
            method_title.setObjectName("sectionHint")
            method_card_layout.addWidget(method_title)

            container = QVBoxLayout()
            container.setSpacing(2)
            method_card_layout.addLayout(container)
            layout.addWidget(method_card)
            self._method_mapping_containers[direction] = container
            help_fields.append((method_card, method_hint))

        # --- متنِ خودکارِ شرحِ ردیف‌هایِ سندِ دریافت ------------------------
        # طبقِ درخواستِ صریح: کاربر خودش می‌تواند متنِ هر روش را بسازد.
        template_card = QWidget()
        template_card.setObjectName("card")
        template_card_layout = QVBoxLayout(template_card)
        template_card_layout.setContentsMargins(12, 10, 12, 10)
        template_card_layout.setSpacing(4)

        template_title = QLabel("متنِ خودکارِ شرحِ ردیف‌هایِ سندِ دریافت")
        template_title.setObjectName("sectionHint")
        template_card_layout.addWidget(template_title)

        template_hint = QLabel(
            "جای‌گذارهایِ مجاز: {تفصیلی} (تفصیلیِ خودِ ردیف)، {مبلغ}، {طرف_حساب} (تفصیلیِ بالایِ فرم)، "
            "{تعداد} (فقط چک)، {یادداشت} (فقط بن)."
        )
        template_hint.setWordWrap(True)
        template_card_layout.addWidget(template_hint)

        self._template_container = QVBoxLayout()
        self._template_container.setSpacing(2)
        template_card_layout.addLayout(self._template_container)
        layout.addWidget(template_card)
        help_fields.append((template_card, "این متن‌ها خودکار در ستونِ «شرح»ِ همان ردیف در فرمِ دریافت پیشنهاد می‌شوند — قابلِ‌ویرایشِ دستی هم هستند."))

        self.set_field_help(help_fields)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        self.company_id = self._company_id()
        if self.company_id is None:
            return
        company_id = self.company_id

        group_options: list[tuple[tuple[str, int], str]] = []
        for g in dimensions_service.list_person_groups(company_id):
            group_options.append((("person", g.person_group_id), g.name))
        for t in dimensions_service.list_dimension_types(company_id):
            label = dimensions_service.SPECIALIZED_DIMENSION_LABELS.get(t.code, t.code)
            group_options.append((("dim", t.dimension_type_id), label))

        account_options = [(a.account_id, f"{a.full_code} — {a.name}") for a in coa_service.list_postable_accounts(company_id)]

        for direction, form in self._forms.items():
            form.set_options(group_options, account_options)
            self.refresh_mappings(direction)

        method_mappings_by_key = {m.mapping_key: m.account_id for m in treasury_service.list_account_mappings(company_id)}
        for direction, container in self._method_mapping_containers.items():
            while container.count():
                child = container.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            self._method_mapping_rows[direction] = []
            for key in _METHOD_KEYS_BY_DIRECTION[direction]:
                row = _MethodMappingRow(
                    key, treasury_service.MAPPING_LABELS[key], method_mappings_by_key.get(key), account_options, self._save_method_mapping
                )
                container.addWidget(row)
                self._method_mapping_rows[direction].append(row)

        while self._template_container.count():
            child = self._template_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._template_rows = []
        for t in treasury_service.list_description_templates(company_id, "RECEIPT"):
            row = _TemplateRow(t.template_key, t.label, t.template_text, self._save_template)
            self._template_container.addWidget(row)
            self._template_rows.append(row)

    def _save_method_mapping(self, mapping_key: str, account_id) -> None:
        if self.company_id is None or account_id is None:
            self.set_status("ابتدا یک حساب انتخاب کنید.")
            return
        treasury_service.set_account_mapping(self.company_id, mapping_key, account_id)
        self.set_status("")

    def _save_template(self, template_key: str, text: str) -> None:
        if self.company_id is None:
            return
        treasury_service.set_description_template(self.company_id, template_key, text)
        self.set_status("")

    def refresh_mappings(self, direction: str) -> None:
        if self.company_id is None:
            return
        table = self._tables[direction]
        rows = treasury_service.list_counterparty_mappings(self.company_id, direction)
        table.setRowCount(len(rows))
        for row_index, r in enumerate(rows):
            values = [r.group_label, r.account_label]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, r.mapping_id)
                table.setItem(row_index, col_index, item)

    def _delete_mapping(self, direction: str, row: int) -> None:
        if self.company_id is None:
            return
        table = self._tables[direction]
        mapping_id = table.item(row, 0).data(Qt.UserRole)
        confirm = QMessageBox.question(
            self, "حذفِ ردیف", "این نگاشت حذف شود؟", QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        treasury_service.delete_counterparty_mapping(mapping_id, self.company_id)
        self.refresh_mappings(direction)
