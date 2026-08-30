"""کاردکسِ کالا -- گردشِ کاملِ یک کالا (ورود/خروج/مانده‌یِ رواگرد) طبقِ
inv.stock_ledger. طبقِ درخواستِ صریح («دکمه‌ای برایِ نمایشِ کاردکسِ کالا»)،
از فرم‌هایِ ردیفِ کالایِ اسنادِ انبار/بازرگانی هم قابلِ بازشدن است
(show_ledger_for_item)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session as app_session
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_engine as engine_service
from peecha.services import inventory_locations as locations_service
from peecha.ui.screens.journal_entry import _fill_options, _make_searchable_combo
from peecha.ui.widgets import JalaliDateEdit

_COLUMNS = ["تاریخ", "نوعِ سند", "شماره‌یِ سند", "انبار", "ورود", "خروج", "بهایِ واحد", "مانده"]


class ItemLedgerScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(10)

        title = QLabel("کاردکسِ کالا")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        filters_row = QHBoxLayout()
        filters_row.addWidget(QLabel("کالا"))
        self.item_combo = _make_searchable_combo([])
        self.item_combo.currentIndexChanged.connect(self._on_filters_changed)
        filters_row.addWidget(self.item_combo, stretch=1)

        filters_row.addWidget(QLabel("انبار"))
        self.warehouse_combo = _make_searchable_combo([])
        self.warehouse_combo.currentIndexChanged.connect(self._on_filters_changed)
        filters_row.addWidget(self.warehouse_combo)

        self.date_filter_checkbox = QCheckBox("فیلترِ تاریخ")
        filters_row.addWidget(self.date_filter_checkbox)
        self.date_from_field = JalaliDateEdit()
        filters_row.addWidget(self.date_from_field)
        filters_row.addWidget(QLabel("تا"))
        self.date_to_field = JalaliDateEdit()
        filters_row.addWidget(self.date_to_field)
        self.date_from_field.setEnabled(False)
        self.date_to_field.setEnabled(False)
        self.date_filter_checkbox.toggled.connect(self._on_date_filter_toggled)
        layout.addLayout(filters_row)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.date_from_field.editingFinished.connect(self._on_filters_changed)
        self.date_to_field.editingFinished.connect(self._on_filters_changed)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        current_item_id = self.item_combo.currentData()
        items = catalog_service.list_items(company_id)
        _fill_options(self.item_combo, [(it.item_id, f"{it.code} — {it.name or ''}") for it in items])
        if current_item_id is not None:
            index = self.item_combo.findData(current_item_id)
            if index >= 0:
                self.item_combo.setCurrentIndex(index)

        current_warehouse_id = self.warehouse_combo.currentData()
        warehouses = locations_service.list_warehouses(company_id)
        _fill_options(self.warehouse_combo, [(w.warehouse_id, w.name) for w in warehouses])
        self.warehouse_combo.setItemText(0, "(همه‌یِ انبارها)")
        if current_warehouse_id is not None:
            index = self.warehouse_combo.findData(current_warehouse_id)
            if index >= 0:
                self.warehouse_combo.setCurrentIndex(index)

        self._refresh_table()

    def show_ledger_for_item(self, item_id: int, warehouse_id: int | None = None) -> None:
        self.refresh()
        index = self.item_combo.findData(item_id)
        if index >= 0:
            self.item_combo.setCurrentIndex(index)
        warehouse_index = self.warehouse_combo.findData(warehouse_id)
        self.warehouse_combo.setCurrentIndex(max(0, warehouse_index))
        self._refresh_table()

    def _on_date_filter_toggled(self, checked: bool) -> None:
        self.date_from_field.setEnabled(checked)
        self.date_to_field.setEnabled(checked)
        self._refresh_table()

    def _on_filters_changed(self) -> None:
        self._refresh_table()

    def _refresh_table(self) -> None:
        self.table.setRowCount(0)
        company_id = self._company_id()
        item_id = self.item_combo.currentData()
        if company_id is None or item_id is None:
            return
        warehouse_id = self.warehouse_combo.currentData()
        use_date_filter = self.date_filter_checkbox.isChecked()
        date_from = self.date_from_field.date() if use_date_filter else None
        date_to = self.date_to_field.date() if use_date_filter else None

        from peecha.ui.screens.inventory_document import DOC_TYPE_TITLES

        rows = engine_service.list_item_ledger(company_id, item_id, warehouse_id, date_from, date_to)
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                numerals.format_jalali_date(row.movement_date),
                DOC_TYPE_TITLES.get(row.document_type_code, row.document_type_code),
                numerals.to_persian_digits(str(row.document_no)),
                row.warehouse_name,
                numerals.format_amount(row.quantity_in) if row.quantity_in else "",
                numerals.format_amount(row.quantity_out) if row.quantity_out else "",
                numerals.format_amount(row.unit_cost) if row.unit_cost is not None else "",
                numerals.format_amount(row.running_balance),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col_index >= 4:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_index, col_index, item)
        self.table.resizeRowsToContents()
        self.status_label.setText("" if rows else "برایِ این کالا (با این فیلترها) هیچ حرکتی ثبت نشده است.")
