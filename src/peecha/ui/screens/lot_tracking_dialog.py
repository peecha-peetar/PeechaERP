"""دیالوگِ ورودِ بچ/سریال/تاریخِ انقضا برایِ یک ردیفِ سند -- R227.

در رسیدِ انبار، تاییدِ رسیدِ سفارشِ خرید، فاکتورِ خرید و امانیِ ورودی استفاده
می‌شود. مقادیر به واحدِ پایهٔ کالا هستند (مثلاً ۲ کارتنِ ۲۴تایی = ۴۸ عدد).
"""

from __future__ import annotations

import decimal

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
    QVBoxLayout,
)

from peecha import numerals
from peecha.services import lot_tracking
from peecha.ui.widgets import JalaliDateEdit

_COLUMNS = ["شمارهٔ بچ", "تاریخِ تولید", "تاریخِ انقضا", "سریال", "مقدار (واحدِ پایه)"]


class LotTrackingDialog(QDialog):
    def __init__(
        self, parent, company_id: int, item_id: int, item_label: str, quantity_base: decimal.Decimal,
        base_uom_label: str = "", *, stock_line_id: int | None = None, commercial_line_id: int | None = None,
        read_only: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ردیابی: بچ / سریال / تاریخِ انقضا")
        self.setMinimumWidth(760)
        self._company_id = company_id
        self._stock_line_id = stock_line_id
        self._commercial_line_id = commercial_line_id
        self._quantity_base = decimal.Decimal(quantity_base)
        self.track_batch, self.track_serial, self.track_expiry = lot_tracking.item_tracking_flags(item_id)
        self._read_only = read_only

        layout = QVBoxLayout(self)
        need = [k for k, on in (("بچ", self.track_batch), ("تاریخِ انقضا", self.track_expiry), ("سریال", self.track_serial)) if on]
        header = QLabel(
            f"«{item_label}» -- مقدارِ ردیف: {numerals.to_persian_digits(str(self._quantity_base.normalize()))} {base_uom_label}"
            + (f" -- الزامی: {'، '.join(need)}" if need else " -- این کالا ردیابیِ بچ/سریال ندارد.")
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setColumnHidden(0, not self.track_batch)
        self.table.setColumnHidden(1, not self.track_batch)
        self.table.setColumnHidden(2, not self.track_batch)
        self.table.setColumnHidden(3, not self.track_serial)
        layout.addWidget(self.table)

        buttons_row = QHBoxLayout()
        self.add_button = QPushButton("➕ ردیف")
        self.add_button.clicked.connect(lambda: self._add_row())
        buttons_row.addWidget(self.add_button)
        self.remove_button = QPushButton("✕ حذفِ ردیف")
        self.remove_button.clicked.connect(self._remove_row)
        buttons_row.addWidget(self.remove_button)
        buttons_row.addStretch(1)
        layout.addLayout(buttons_row)

        if self.track_serial:
            serial_hint = QLabel("ورودِ گروهیِ سریال‌ها (هر سطر یک سریال؛ اسکنِ پشتِ‌سرِهم با بارکدخوان):")
            layout.addWidget(serial_hint)
            self.bulk_serials = QPlainTextEdit()
            self.bulk_serials.setFixedHeight(80)
            layout.addWidget(self.bulk_serials)
            bulk_row = QHBoxLayout()
            bulk_row.addWidget(QLabel("بچِ مشترک (اختیاری):"))
            self.bulk_batch = QLineEdit()
            bulk_row.addWidget(self.bulk_batch)
            bulk_row.addWidget(QLabel("انقضا:"))
            self.bulk_expiry = JalaliDateEdit(allow_empty=True)
            bulk_row.addWidget(self.bulk_expiry)
            bulk_button = QPushButton("افزودنِ سریال‌ها")
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

        existing = (
            lot_tracking.get_line_tracking(stock_line_id=stock_line_id) if stock_line_id is not None
            else lot_tracking.get_effective_commercial_tracking(commercial_line_id)
        )
        for e in existing:
            self._add_row(e)
        if not existing and not self.track_serial:
            self._add_row(lot_tracking.TrackingEntry(self._quantity_base))
        for w in (self.add_button, self.remove_button):
            w.setEnabled(not read_only)
        self._update_total()

    def _add_row(self, entry: lot_tracking.TrackingEntry | None = None) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        batch = QLineEdit((entry.batch_no or "") if entry else "")
        mfg = JalaliDateEdit(allow_empty=True)
        mfg.setDate(entry.manufacture_date if entry else None)
        exp = JalaliDateEdit(allow_empty=True)
        exp.setDate(entry.expiry_date if entry else None)
        serial = QLineEdit((entry.serial_no or "") if entry else "")
        qty = QLineEdit(str((entry.quantity if entry else decimal.Decimal(1)).normalize()))
        qty.setAlignment(Qt.AlignCenter)
        if self.track_serial:
            qty.setText("1")
            qty.setEnabled(False)
        qty.textChanged.connect(self._update_total)
        for col, w in enumerate((batch, mfg, exp, serial, qty)):
            w.setEnabled(w.isEnabled() and not self._read_only)
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
            batch, mfg, exp, serial, qty = (self.table.cellWidget(r, c) for c in range(5))
            try:
                quantity = decimal.Decimal(numerals.to_ascii_digits(qty.text().strip() or "0"))
            except decimal.InvalidOperation:
                quantity = decimal.Decimal(0)
            if quantity <= 0 and not batch.text().strip() and not serial.text().strip():
                continue
            result.append(lot_tracking.TrackingEntry(
                quantity, batch_no=batch.text().strip() or None, manufacture_date=mfg.date(),
                expiry_date=exp.date(), serial_no=serial.text().strip() or None,
            ))
        return result

    def _update_total(self, *_args) -> None:
        total = sum((e.quantity for e in self.entries()), decimal.Decimal(0))
        self.total_label.setText(
            f"واردشده: {numerals.to_persian_digits(str(total.normalize()))} از "
            f"{numerals.to_persian_digits(str(self._quantity_base.normalize()))}"
        )

    def _save(self) -> None:
        try:
            lot_tracking.set_line_tracking(
                self._company_id, self.entries(), stock_line_id=self._stock_line_id,
                commercial_line_id=self._commercial_line_id,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "ردیابی", str(exc))
            return
        self.accept()
