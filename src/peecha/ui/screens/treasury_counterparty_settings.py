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


class TreasuryCounterpartySettingsScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.company_id: int | None = None
        self._forms: dict[str, _MappingForm] = {}
        self._tables: dict[str, QTableWidget] = {}

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
