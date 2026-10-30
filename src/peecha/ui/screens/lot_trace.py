"""ردیابی بچ/سریال/انقضا و کالای امانی — R227.

تب «موجودی ردیابی»: موجودی هر بچ/سریال در هر انبار، با تاریخ انقضا و
تامین‌کننده (و جدا شدن کالای امانی). تب «تاریخچه»: مسیر کامل یک بچ/سریال/
کالای یک تامین‌کننده از ورود تا خروج. همهٔ منطق در services/lot_tracking.py.
"""

from __future__ import annotations

import datetime

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from peecha import decimals, numerals, session as app_session
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.services import lot_tracking

_BALANCE_COLUMNS = ["کالا", "انبار", "بچ", "تاریخ تولید", "تاریخ انقضا", "سریال", "تامین‌کننده", "امانی", "موجودی"]
_TRACE_COLUMNS = ["زمان", "سند", "کالا", "انبار", "بچ", "سریال", "تامین‌کننده", "امانی", "مقدار"]


def _table(columns: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(40)
    table.setAlternatingRowColors(True)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    return table


def _date(value: datetime.date | None) -> str:
    return numerals.format_jalali_date(value) if value else ""


class LotTraceScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)
        title = QLabel("ردیابی بچ / سریال / انقضا و کالای امانی")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, stretch=1)

        # --- موجودیِ ردیابی
        balance_tab = QWidget()
        b_layout = QVBoxLayout(balance_tab)
        filters = QHBoxLayout()
        self.item_combo = QComboBox()
        self.warehouse_combo = QComboBox()
        self.supplier_combo = QComboBox()
        self.consignment_only = QCheckBox("فقط امانی")
        self.expiring_days = QSpinBox()
        self.expiring_days.setRange(0, 3650)
        self.expiring_days.setSuffix(" روز")
        self.expiring_days.setSpecialValueText("همه")
        self.expiring_days.setToolTip("فقط بچ‌هایی که تا این تعداد روز آینده منقضی می‌شوند (۰ = همه)")
        for label, w in (("کالا", self.item_combo), ("انبار", self.warehouse_combo), ("تامین‌کننده", self.supplier_combo)):
            filters.addWidget(QLabel(label))
            filters.addWidget(w, stretch=1)
        filters.addWidget(self.consignment_only)
        filters.addWidget(QLabel("انقضا تا"))
        filters.addWidget(self.expiring_days)
        show_button = QPushButton("نمایش")
        show_button.setObjectName("primaryButton")
        show_button.clicked.connect(self._load_balances)
        filters.addWidget(show_button)
        b_layout.addLayout(filters)
        self.balance_table = _table(_BALANCE_COLUMNS)
        self.balance_table.cellDoubleClicked.connect(self._trace_from_balance)
        b_layout.addWidget(self.balance_table)
        self.tabs.addTab(balance_tab, "موجودی ردیابی")

        # --- تاریخچه
        trace_tab = QWidget()
        t_layout = QVBoxLayout(trace_tab)
        t_filters = QHBoxLayout()
        self.batch_field = QLineEdit()
        self.batch_field.setPlaceholderText("شمارهٔ بچ")
        self.serial_field = QLineEdit()
        self.serial_field.setPlaceholderText("شمارهٔ سریال")
        self.trace_supplier_combo = QComboBox()
        t_filters.addWidget(self.batch_field)
        t_filters.addWidget(self.serial_field)
        t_filters.addWidget(QLabel("تامین‌کننده"))
        t_filters.addWidget(self.trace_supplier_combo, stretch=1)
        trace_button = QPushButton("ردیابی")
        trace_button.setObjectName("primaryButton")
        trace_button.clicked.connect(self._load_trace)
        t_filters.addWidget(trace_button)
        t_layout.addLayout(t_filters)
        self.trace_table = _table(_TRACE_COLUMNS)
        t_layout.addWidget(self.trace_table)
        self.tabs.addTab(trace_tab, "تاریخچهٔ حرکت")

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        for combo, rows in (
            (self.item_combo, [(f"{i.code} — {i.name or ''}", i.item_id) for i in catalog_service.list_items(company_id)]),
            (self.warehouse_combo, [(w.name, w.warehouse_id) for w in locations_service.list_warehouses(company_id)]),
            (self.supplier_combo, [(s["name"], s["detail_account_id"]) for s in dimensions_service.list_suppliers(company_id)]),
            (self.trace_supplier_combo, [(s["name"], s["detail_account_id"]) for s in dimensions_service.list_suppliers(company_id)]),
        ):
            current = combo.currentData()
            combo.clear()
            combo.addItem("(همه)", None)
            for label, value in rows:
                combo.addItem(label, value)
            combo.setCurrentIndex(max(0, combo.findData(current)))
        self._load_balances()

    def _load_balances(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        days = self.expiring_days.value()
        rows = lot_tracking.list_lot_balances(
            company_id, item_id=self.item_combo.currentData(), warehouse_id=self.warehouse_combo.currentData(),
            supplier_detail_account_id=self.supplier_combo.currentData(),
            consignment_only=self.consignment_only.isChecked(),
            expiring_before=(datetime.date.today() + datetime.timedelta(days=days)) if days else None,
        )
        self._balance_rows = rows
        self.balance_table.setRowCount(len(rows))
        today = datetime.date.today()
        for r, row in enumerate(rows):
            expiry = _date(row.expiry_date)
            if row.expiry_date is not None and row.expiry_date < today:
                expiry += " (منقضی)"
            values = [
                row.item_label, row.warehouse_label, row.batch_no or "", _date(row.manufacture_date), expiry,
                row.serial_no or "", row.supplier_name or "", "امانی" if row.is_consignment else "",
                decimals.format_qty(row.quantity),
            ]
            for c, v in enumerate(values):
                self.balance_table.setItem(r, c, QTableWidgetItem(numerals.to_persian_digits(v) if c in (2, 5) else v))

    def _trace_from_balance(self, row: int, _col: int) -> None:
        if not (0 <= row < len(getattr(self, "_balance_rows", []))):
            return
        data = self._balance_rows[row]
        self.batch_field.setText(data.batch_no or "")
        self.serial_field.setText(data.serial_no or "")
        self.trace_supplier_combo.setCurrentIndex(
            max(0, self.trace_supplier_combo.findData(data.supplier_detail_account_id))
            if not data.batch_no and not data.serial_no else 0
        )
        self.tabs.setCurrentIndex(1)
        self._load_trace(item_id=data.item_id)

    def _load_trace(self, *_args, item_id: int | None = None) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        rows = lot_tracking.trace(
            company_id, batch_no=numerals.to_ascii_digits(self.batch_field.text().strip()) or None,
            serial_no=numerals.to_ascii_digits(self.serial_field.text().strip()) or None,
            item_id=item_id, supplier_detail_account_id=self.trace_supplier_combo.currentData(),
        )
        self.trace_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = [
                numerals.format_jalali_datetime(row.created_at), numerals.to_persian_digits(row.document_label),
                row.item_label, row.warehouse_label, row.batch_no or "", row.serial_no or "",
                row.supplier_name or "", "امانی" if row.is_consignment else "", decimals.format_qty(row.quantity),
            ]
            for c, v in enumerate(values):
                self.trace_table.setItem(r, c, QTableWidgetItem(v))
