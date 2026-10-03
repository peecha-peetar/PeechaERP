"""اطلاعاتِ پایهٔ تدارکات -- R240: انواعِ خرید، علت‌هایِ لغو، سیاستِ سفارشِ کالا."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QCompleter, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from peecha import numerals, session
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import procurement_masters as masters_service


def _company_id() -> int | None:
    return session.current_company.company_id if session.current_company else None


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    return table


def _fill_table(table: QTableWidget, rows: list[list]) -> None:
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.setItem(r, c, QTableWidgetItem(numerals.to_persian_digits("" if value is None else str(value))))


def _qty(value) -> str:
    return "" if value is None else numerals.format_money(value, 2, None)


class _CodeNameTab(QWidget):
    """جدول + فرمِ کد/عنوان/فعال (و در صورتِ نیاز «اضطراری»)."""

    def __init__(self, headers: list[str], with_emergency: bool) -> None:
        super().__init__()
        self._with_emergency = with_emergency
        self._rows: list = []
        self._editing_id: int | None = None
        layout = QVBoxLayout(self)
        self.table = _table(headers)
        self.table.itemSelectionChanged.connect(self._load_selected)
        layout.addWidget(self.table, stretch=1)
        form = QHBoxLayout()
        self.code_field, self.name_field = QLineEdit(), QLineEdit()
        self.code_field.setMaximumWidth(140)
        self.emergency_check = QCheckBox("اضطراری")
        self.active_check = QCheckBox("فعال")
        self.active_check.setChecked(True)
        for text, widget in (("کد:", self.code_field), ("عنوان:", self.name_field)):
            form.addWidget(QLabel(text))
            form.addWidget(widget)
        if with_emergency:
            form.addWidget(self.emergency_check)
        form.addWidget(self.active_check)
        new_button, save_button = QPushButton("جدید"), QPushButton("ذخیره")
        save_button.setObjectName("primaryButton")
        new_button.clicked.connect(self.clear_form)
        save_button.clicked.connect(self.save)
        form.addWidget(new_button)
        form.addWidget(save_button)
        layout.addLayout(form)

    def clear_form(self) -> None:
        self._editing_id = None
        self.code_field.clear()
        self.name_field.clear()
        self.emergency_check.setChecked(False)
        self.active_check.setChecked(True)
        self.table.clearSelection()

    def _load_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(self._rows):
            return
        row = self._rows[rows[0].row()]
        self._editing_id = self.row_id(row)
        self.code_field.setText(row.code)
        self.name_field.setText(row.name)
        self.emergency_check.setChecked(bool(getattr(row, "is_emergency", False)))
        self.active_check.setChecked(row.is_active)

    def save(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        try:
            self.persist(company_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.clear_form()
        self.refresh()

    def row_id(self, row) -> int:
        raise NotImplementedError

    def persist(self, company_id: int) -> None:
        raise NotImplementedError

    def refresh(self) -> None:
        raise NotImplementedError


class _PurchaseTypesTab(_CodeNameTab):
    def __init__(self) -> None:
        super().__init__(["کد", "عنوان", "اضطراری", "فعال"], with_emergency=True)

    def row_id(self, row) -> int:
        return row.purchase_type_id

    def persist(self, company_id: int) -> None:
        masters_service.save_purchase_type(company_id, self.code_field.text(), self.name_field.text(),
                                           self.emergency_check.isChecked(), self.active_check.isChecked(), self._editing_id)

    def refresh(self) -> None:
        company_id = _company_id()
        self._rows = masters_service.list_purchase_types(company_id) if company_id else []
        _fill_table(self.table, [[r.code, r.name, "بله" if r.is_emergency else "خیر", "بله" if r.is_active else "خیر"]
                                 for r in self._rows])


class _CancelReasonsTab(_CodeNameTab):
    def __init__(self) -> None:
        super().__init__(["کد", "عنوان", "فعال"], with_emergency=False)

    def row_id(self, row) -> int:
        return row.reason_id

    def persist(self, company_id: int) -> None:
        masters_service.save_cancellation_reason(company_id, self.code_field.text(), self.name_field.text(),
                                                 self.active_check.isChecked(), self._editing_id)

    def refresh(self) -> None:
        company_id = _company_id()
        self._rows = masters_service.list_cancellation_reasons(company_id) if company_id else []
        _fill_table(self.table, [[r.code, r.name, "بله" if r.is_active else "خیر"] for r in self._rows])


class _ReorderPoliciesTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list = []
        self._editing_id: int | None = None
        self._items: dict[int, str] = {}
        self._warehouses: dict[int, str] = {}
        layout = QVBoxLayout(self)
        hint = QLabel("حداقل ≤ نقطهٔ سفارش < حداکثر. این مقادیر در گزارش‌هایِ «وضعیتِ موجودی»، «پیشنهادِ خرید» و "
                      "«تحلیلِ نقطهٔ سفارش» استفاده می‌شوند؛ کالایِ بدونِ سیاست از پیش‌فرضِ انبار پیروی می‌کند.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = _table(["کالا", "انبار", "حداقل", "نقطهٔ سفارش", "حداکثر", "مقدارِ سفارش", "زمانِ تحویل (روز)", "فعال"])
        self.table.itemSelectionChanged.connect(self._load_selected)
        layout.addWidget(self.table, stretch=1)
        form = QHBoxLayout()
        self.item_combo = QComboBox()
        self.item_combo.setEditable(True)
        self.item_combo.setInsertPolicy(QComboBox.NoInsert)
        self.item_combo.setMinimumWidth(220)
        self.warehouse_combo = QComboBox()
        self.min_field, self.rop_field, self.max_field, self.qty_field = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        for field in (self.min_field, self.rop_field, self.max_field, self.qty_field):
            field.setMaximumWidth(90)
        self.lead_spin = QSpinBox()
        self.lead_spin.setRange(0, 365)
        self.active_check = QCheckBox("فعال")
        self.active_check.setChecked(True)
        for text, widget in (("کالا:", self.item_combo), ("انبار:", self.warehouse_combo), ("حداقل:", self.min_field),
                             ("نقطهٔ سفارش:", self.rop_field), ("حداکثر:", self.max_field), ("مقدارِ سفارش:", self.qty_field),
                             ("زمانِ تحویل:", self.lead_spin)):
            form.addWidget(QLabel(text))
            form.addWidget(widget)
        form.addWidget(self.active_check)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for text, slot, primary in (("جدید", self.clear_form, False), ("حذف", self.delete, False), ("ذخیره", self.save, True)):
            button = QPushButton(text)
            if primary:
                button.setObjectName("primaryButton")
            button.clicked.connect(slot)
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        self._items = {i.item_id: f"{i.code} — {i.name or ''}" for i in catalog_service.list_items(company_id, transactable_only=True)
                       if i.is_stock_tracked}
        self._warehouses = {w.warehouse_id: f"{w.code} — {w.name}" for w in locations_service.list_warehouses(company_id)}
        self.item_combo.clear()
        for item_id, label in self._items.items():
            self.item_combo.addItem(numerals.to_persian_digits(label), item_id)
        completer = QCompleter([self.item_combo.itemText(i) for i in range(self.item_combo.count())])
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.item_combo.setCompleter(completer)
        self.warehouse_combo.clear()
        self.warehouse_combo.addItem("همهٔ انبارها", None)
        for warehouse_id, label in self._warehouses.items():
            self.warehouse_combo.addItem(numerals.to_persian_digits(label), warehouse_id)
        self._rows = masters_service.list_reorder_policies(company_id)
        _fill_table(self.table, [[
            self._items.get(p.item_id, p.item_id), self._warehouses.get(p.warehouse_id, "همهٔ انبارها") if p.warehouse_id else "همهٔ انبارها",
            _qty(p.min_qty), _qty(p.reorder_point_qty), _qty(p.max_qty), _qty(p.reorder_qty), p.lead_time_days or "",
            "بله" if p.is_active else "خیر",
        ] for p in self._rows])

    def clear_form(self) -> None:
        self._editing_id = None
        for field in (self.min_field, self.rop_field, self.max_field, self.qty_field):
            field.clear()
        self.lead_spin.setValue(0)
        self.active_check.setChecked(True)
        self.warehouse_combo.setCurrentIndex(0)
        self.table.clearSelection()

    def _load_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(self._rows):
            return
        p = self._rows[rows[0].row()]
        self._editing_id = p.policy_id
        self.item_combo.setCurrentIndex(max(0, self.item_combo.findData(p.item_id)))
        self.warehouse_combo.setCurrentIndex(max(0, self.warehouse_combo.findData(p.warehouse_id)))
        for field, value in ((self.min_field, p.min_qty), (self.rop_field, p.reorder_point_qty), (self.max_field, p.max_qty),
                             (self.qty_field, p.reorder_qty)):
            field.setText(numerals.to_persian_digits(format(value.normalize(), "f")) if value is not None else "")
        self.lead_spin.setValue(p.lead_time_days or 0)
        self.active_check.setChecked(p.is_active)

    def fields(self) -> masters_service.PolicyFields:
        def number(field: QLineEdit):
            return numerals.parse_decimal(field.text()) if field.text().strip() else None

        return masters_service.PolicyFields(
            item_id=self.item_combo.currentData(), warehouse_id=self.warehouse_combo.currentData(),
            min_qty=number(self.min_field), max_qty=number(self.max_field), reorder_point_qty=number(self.rop_field),
            reorder_qty=number(self.qty_field), lead_time_days=self.lead_spin.value() or None, is_active=self.active_check.isChecked(),
        )

    def save(self) -> None:
        company_id = _company_id()
        if company_id is None or self.item_combo.currentData() is None:
            return
        try:
            masters_service.save_reorder_policy(company_id, self.fields(), self._editing_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.clear_form()
        self.refresh()

    def delete(self) -> None:
        company_id = _company_id()
        if company_id is None or self._editing_id is None:
            return
        if QMessageBox.question(self, "حذف", "این سیاستِ سفارش حذف شود؟") != QMessageBox.Yes:
            return
        masters_service.delete_reorder_policy(company_id, self._editing_id)
        self.clear_form()
        self.refresh()


class ProcurementMastersScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        title = QLabel("اطلاعاتِ پایهٔ تدارکات")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.tabs = QTabWidget()
        self.purchase_types_tab = _PurchaseTypesTab()
        self.cancel_reasons_tab = _CancelReasonsTab()
        self.policies_tab = _ReorderPoliciesTab()
        self.tabs.addTab(self.purchase_types_tab, "انواعِ خرید")
        self.tabs.addTab(self.cancel_reasons_tab, "علت‌هایِ لغو")
        self.tabs.addTab(self.policies_tab, "سیاستِ سفارشِ کالا")
        layout.addWidget(self.tabs, stretch=1)

    def refresh(self) -> None:
        for tab in (self.purchase_types_tab, self.cancel_reasons_tab, self.policies_tab):
            tab.refresh()
