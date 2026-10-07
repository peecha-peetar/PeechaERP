"""دیالوگ ورود/انتخاب بچ/سریال/تاریخ انقضا برای یک ردیف سند — R227/R228.

سه حالت:
- IN  (رسید، تایید رسید سفارش خرید، فاکتور خرید، امانی ورودی): ورود بچ/انقضا/سریال.
- OUT (فروش، حواله، برگشت به تامین‌کننده، انتقال): جدول «موجودی قابل‌انتخاب» در
  انبار سند — هر بچ/سریال با انقضا، تامین‌کننده و امانی/خریداری‌شده — تا کاربر
  دقیقاً همان منبع را انتخاب کند (حتی کالای امانی یک تامین‌کنندهٔ خاص بدون بچ/سریال).
- COUNT (انبارگردانی): موجودی دفتری هر بچ/سریال پیش‌پر می‌شود و کاربر شمارش واقعی را وارد می‌کند.
مقادیر به واحد پایهٔ کالا هستند.
"""

from __future__ import annotations

import decimal
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from peecha import decimals, numerals
from peecha.services import lot_tracking
from peecha.ui.widgets import JalaliDateEdit

_COLUMNS = ["شمارهٔ بچ", "تاریخ تولید", "تاریخ انقضا", "سریال", "منبع", "مقدار (واحد پایه)"]
_AVAILABLE_COLUMNS = ["بچ", "تاریخ انقضا", "سریال", "تامین‌کننده", "نوع", "موجودی"]


def _style_table(table: QTableWidget, row_height: int) -> None:
    table.verticalHeader().setVisible(False)
    # R228: ردیف‌ها بلندتر تا فیلدها/تاریخ‌هایِ داخلِ سلول کامل دیده شوند
    table.verticalHeader().setDefaultSectionSize(row_height)
    table.verticalHeader().setMinimumSectionSize(row_height - 4)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)


class LotTrackingDialog(QDialog):
    def __init__(
        self, parent, company_id: int, item_id: int, item_label: str, quantity_base: decimal.Decimal | None,
        base_uom_label: str = "", *, stock_line_id: int | None = None, commercial_line_id: int | None = None,
        cycle_count_line_id: int | None = None, read_only: bool = False, direction: str = "IN",
        warehouse_id: int | None = None, on_save: Callable[[list[lot_tracking.TrackingEntry]], None] | None = None,
        initial_entries: list[lot_tracking.TrackingEntry] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle({
            "OUT": "انتخاب بچ / سریال / منبع کالا", "COUNT": "انبارگردانی به تفکیک بچ / سریال",
        }.get(direction, "ردیابی: بچ / سریال / تاریخ انقضا"))
        self.setMinimumWidth(960)
        self.resize(1040, 720 if direction in ("OUT", "COUNT") else 620)
        self._company_id = company_id
        self._item_id = item_id
        self._stock_line_id = stock_line_id
        self._commercial_line_id = commercial_line_id
        self._cycle_count_line_id = cycle_count_line_id
        self._direction = direction
        self._on_save = on_save
        self._quantity_base = decimal.Decimal(quantity_base) if quantity_base is not None else None
        self.track_batch, self.track_serial, self.track_expiry = lot_tracking.item_tracking_flags(item_id)
        self._read_only = read_only
        self._available: list[lot_tracking.LotBalanceRow] = []

        layout = QVBoxLayout(self)
        need = [k for k, on in (("بچ", self.track_batch), ("تاریخ انقضا", self.track_expiry), ("سریال", self.track_serial)) if on]
        qty_text = (
            f" -- مقدار ردیف: {decimals.format_qty(self._quantity_base)} {base_uom_label}"
            if self._quantity_base is not None else ""
        )
        header = QLabel(
            f"«{item_label}»{qty_text}"
            + (f" -- {'الزامی' if direction == 'IN' else 'ردیابی'}: {'، '.join(need)}" if need else " -- بدون بچ/سریال (ردیابی بر اساس تامین‌کننده/امانی).")
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        if direction in ("OUT", "COUNT") and warehouse_id is not None:
            hint = QLabel(
                "موجودی قابل‌انتخاب در همین انبار — ردیف(ها) را انتخاب و «افزودن انتخاب‌شده‌ها» را بزنید:"
                if direction == "OUT" else "موجودی دفتری هر بچ/سریال در این انبار:"
            )
            layout.addWidget(hint)
            self.available_table = QTableWidget(0, len(_AVAILABLE_COLUMNS))
            self.available_table.setHorizontalHeaderLabels(_AVAILABLE_COLUMNS)
            _style_table(self.available_table, 38)
            self.available_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.available_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
            self.available_table.setMinimumHeight(180)
            self.available_table.cellDoubleClicked.connect(lambda *_: self._add_selected_available())
            layout.addWidget(self.available_table, stretch=1)
            if direction == "OUT":
                pick_button = QPushButton("⬇ افزودن انتخاب‌شده‌ها")
                pick_button.setObjectName("primaryButton")
                pick_button.setEnabled(not read_only)
                pick_button.clicked.connect(self._add_selected_available)
                layout.addWidget(pick_button)
            self._load_available(warehouse_id)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        _style_table(self.table, 46)
        self.table.setMinimumHeight(240)
        self.table.setColumnHidden(0, not self.track_batch)
        self.table.setColumnHidden(1, not self.track_batch or direction != "IN")
        self.table.setColumnHidden(2, not self.track_batch)
        self.table.setColumnHidden(3, not self.track_serial)
        self.table.setColumnHidden(4, direction != "OUT")
        layout.addWidget(self.table, stretch=2)

        buttons_row = QHBoxLayout()
        self.add_button = QPushButton("➕ ردیف")
        self.add_button.clicked.connect(lambda: self._add_row())
        buttons_row.addWidget(self.add_button)
        self.remove_button = QPushButton("✕ حذف ردیف")
        self.remove_button.clicked.connect(self._remove_row)
        buttons_row.addWidget(self.remove_button)
        buttons_row.addStretch(1)
        layout.addLayout(buttons_row)

        if self.track_serial and direction in ("IN", "COUNT"):
            layout.addWidget(QLabel("ورود گروهی سریال‌ها (هر سطر یک سریال؛ اسکن پشت‌سرهم با بارکدخوان):"))
            self.bulk_serials = QPlainTextEdit()
            self.bulk_serials.setFixedHeight(80)
            layout.addWidget(self.bulk_serials)
            bulk_row = QHBoxLayout()
            bulk_row.addWidget(QLabel("بچ مشترک (اختیاری):"))
            self.bulk_batch = QLineEdit()
            bulk_row.addWidget(self.bulk_batch)
            bulk_row.addWidget(QLabel("انقضا:"))
            self.bulk_expiry = JalaliDateEdit(allow_empty=True)
            bulk_row.addWidget(self.bulk_expiry)
            bulk_button = QPushButton("افزودن سریال‌ها")
            bulk_button.clicked.connect(self._add_bulk_serials)
            bulk_row.addWidget(bulk_button)
            layout.addLayout(bulk_row)

        self.total_label = QLabel("")
        layout.addWidget(self.total_label)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText("ذخیره")
        box.button(QDialogButtonBox.Cancel).setText("انصراف")
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        box.button(QDialogButtonBox.Ok).setEnabled(not read_only)
        layout.addWidget(box)

        if initial_entries is not None:
            existing = initial_entries
        elif stock_line_id is not None:
            existing = lot_tracking.get_line_tracking(stock_line_id=stock_line_id)
        elif cycle_count_line_id is not None:
            existing = lot_tracking.get_line_tracking(cycle_count_line_id=cycle_count_line_id)
        elif commercial_line_id is not None:
            existing = lot_tracking.get_effective_commercial_tracking(commercial_line_id)
        else:
            existing = []
        if not existing and direction == "COUNT" and warehouse_id is not None:
            existing = lot_tracking.expected_tracking(company_id, item_id, warehouse_id)
        for e in existing:
            self._add_row(e)
        if not existing and direction == "IN" and not self.track_serial and self._quantity_base is not None:
            self._add_row(lot_tracking.TrackingEntry(self._quantity_base))
        for w in (self.add_button, self.remove_button):
            w.setEnabled(not read_only)
        self._update_total()

    # --- موجودیِ قابلِ‌انتخاب
    def _load_available(self, warehouse_id: int) -> None:
        self._available = lot_tracking.list_lot_balances(self._company_id, item_id=self._item_id, warehouse_id=warehouse_id)
        self.available_table.setRowCount(len(self._available))
        for r, row in enumerate(self._available):
            values = [
                numerals.to_persian_digits(row.batch_no or ""),
                numerals.format_jalali_date(row.expiry_date) if row.expiry_date else "",
                numerals.to_persian_digits(row.serial_no or ""),
                row.supplier_name or "",
                "امانی" if row.is_consignment else "خریداری‌شده",
                decimals.format_qty(row.quantity),
            ]
            for c, v in enumerate(values):
                self.available_table.setItem(r, c, QTableWidgetItem(v))

    def _add_selected_available(self) -> None:
        rows = sorted({i.row() for i in self.available_table.selectedIndexes()})
        remaining = None
        if self._quantity_base is not None:
            remaining = self._quantity_base - sum((e.quantity for e in self.entries()), decimal.Decimal(0))
        for r in rows:
            pool = self._available[r]
            qty = pool.quantity if remaining is None else min(pool.quantity, max(remaining, decimal.Decimal(0)))
            if pool.serial_no:
                qty = decimal.Decimal(1)
            if qty <= 0:
                break
            self._add_row(lot_tracking.TrackingEntry(
                qty, batch_no=pool.batch_no, manufacture_date=pool.manufacture_date, expiry_date=pool.expiry_date,
                serial_no=pool.serial_no, supplier_detail_account_id=pool.supplier_detail_account_id,
                is_consignment=pool.is_consignment,
            ), source_label=f"{pool.supplier_name or '—'} ({'امانی' if pool.is_consignment else 'خریداری‌شده'})")
            if remaining is not None:
                remaining -= qty
        self._update_total()

    # --- ردیف‌ها
    def _add_row(self, entry: lot_tracking.TrackingEntry | None = None, source_label: str | None = None) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        batch = QLineEdit((entry.batch_no or "") if entry else "")
        mfg = JalaliDateEdit(allow_empty=True)
        mfg.setDate(entry.manufacture_date if entry else None)
        exp = JalaliDateEdit(allow_empty=True)
        exp.setDate(entry.expiry_date if entry else None)
        serial = QLineEdit((entry.serial_no or "") if entry else "")
        if source_label is None and entry is not None and (entry.supplier_detail_account_id or entry.is_consignment is not None):
            source_label = "امانی" if entry.is_consignment else "خریداری‌شده"
        source = QLabel(source_label or "")
        source.setProperty("supplier_id", entry.supplier_detail_account_id if entry else None)
        source.setProperty("is_consignment", entry.is_consignment if entry else None)
        qty = QLineEdit(decimals.plain(entry.quantity if entry else decimal.Decimal(1)))
        qty.setAlignment(Qt.AlignCenter)
        if self.track_serial:
            qty.setText("1")
            qty.setEnabled(False)
        qty.textChanged.connect(self._update_total)
        for col, w in enumerate((batch, mfg, exp, serial, source, qty)):
            w.setEnabled(w.isEnabled() and not self._read_only)
            w.setMinimumHeight(34)
            self.table.setCellWidget(r, col, w)

    def _remove_row(self) -> None:
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)
            self._update_total()

    def _add_bulk_serials(self) -> None:
        serials = [s.strip() for s in self.bulk_serials.toPlainText().splitlines() if s.strip()]
        for s in serials:
            self._add_row(lot_tracking.TrackingEntry(
                decimal.Decimal(1), batch_no=self.bulk_batch.text().strip() or None,
                expiry_date=self.bulk_expiry.date(), serial_no=s,
            ))
        self.bulk_serials.clear()
        self._update_total()

    def entries(self) -> list[lot_tracking.TrackingEntry]:
        result = []
        for r in range(self.table.rowCount()):
            batch, mfg, exp, serial, source, qty = (self.table.cellWidget(r, c) for c in range(6))
            try:
                quantity = decimal.Decimal(numerals.to_ascii_digits(qty.text().strip() or "0"))
            except decimal.InvalidOperation:
                quantity = decimal.Decimal(0)
            if quantity <= 0:
                continue
            result.append(lot_tracking.TrackingEntry(
                quantity, batch_no=numerals.to_ascii_digits(batch.text().strip()) or None, manufacture_date=mfg.date(),
                expiry_date=exp.date(), serial_no=numerals.to_ascii_digits(serial.text().strip()) or None,
                supplier_detail_account_id=source.property("supplier_id"), is_consignment=source.property("is_consignment"),
            ))
        return result

    def _update_total(self, *_args) -> None:
        total = sum((e.quantity for e in self.entries()), decimal.Decimal(0))
        text = f"{'شمارش‌شده' if self._direction == 'COUNT' else 'واردشده'}: {decimals.format_qty(total)}"
        if self._quantity_base is not None:
            text += f" از {decimals.format_qty(self._quantity_base)}"
        self.total_label.setText(text)

    def _save(self) -> None:
        try:
            if self._on_save is not None:
                self._on_save(self.entries())
            else:
                lot_tracking.set_line_tracking(
                    self._company_id, self.entries(), stock_line_id=self._stock_line_id,
                    commercial_line_id=self._commercial_line_id, cycle_count_line_id=self._cycle_count_line_id,
                )
        except ValueError as exc:
            QMessageBox.warning(self, "ردیابی", str(exc))
            return
        self.accept()
