"""R349: تسعیر ارز — پیش‌نمایش ماندهٔ ارزی حساب‌های دائم با نرخ تاریخ تسعیر، ثبت سند سود و زیان تسعیر و برگرداندن آن."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidgetItem, QVBoxLayout, QWidget,
)

from peecha import numerals
from peecha.services import chart_of_accounts as coa_service
from peecha.services import fx_revaluation as fx_service
from peecha.ui import theme
from peecha.ui.screens.fixed_assets import P, combo, company_id, dec, fill, money, set_combo, table, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec, JalaliDateEdit, build_page_header

_STATUS = {"TEMPORARY": "موقت", "PERMANENT": "قطعی", "DRAFT": "پیش‌نویس"}


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName("primaryIconButton" if kind == "primary" else "iconButton")
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


class FxRevaluationScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.info: fx_service.Preview | None = None
        self.history: list[fx_service.RevaluationRow] = []
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "تسعیر ارز", "ماندهٔ ارزی حساب‌های دائم با نرخ تاریخ تسعیر به ریال برگردانده و تفاوتش سود یا زیان تسعیر ثبت می‌شود."))
        self.date_field = JalaliDateEdit()
        self.date_field.setDate(datetime.date.today())
        self.gain_combo, self.loss_combo = combo([], "— انتخاب —"), combo([], "— انتخاب —")
        layout.addWidget(FieldGrid([
            FieldSpec("revaluation_date", "تاریخ تسعیر", self.date_field, span=1),
            FieldSpec("fx_gain_account", "حساب سود تسعیر", self.gain_combo, span=1),
            FieldSpec("fx_loss_account", "حساب زیان تسعیر", self.loss_combo, span=1),
        ]))
        rates_title = QLabel("نرخ ارزها در تاریخ تسعیر (قابل ویرایش)")
        rates_title.setObjectName("sectionTitle")
        layout.addWidget(rates_title)
        self.rates_table = table(["ارز", "نرخ به ریال"])
        self.rates_table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.rates_table.setMaximumHeight(140)
        layout.addWidget(self.rates_table)
        self.table = table(["تسعیر شود", "حساب", "تفصیلی", "ارز", "ماندهٔ ارزی", "ماندهٔ ریالی فعلی", "نرخ",
                            "ماندهٔ ریالی تسعیرشده", "سود (زیان) تسعیر"])
        layout.addWidget(self.table, 2)
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        bar = QHBoxLayout()
        self.preview_button = _btn("محاسبهٔ پیش‌نمایش با نرخ‌های جدول", "🔄")
        self.run_button = _btn("ثبت سند تسعیر", "✅", "primary")
        for button, handler in ((self.preview_button, self.load_preview), (self.run_button, self.run)):
            button.clicked.connect(handler)
            bar.addWidget(button)
        bar.addStretch(1)
        layout.addLayout(bar)
        history_title = QLabel("تسعیرهای انجام‌شده")
        history_title.setObjectName("sectionTitle")
        layout.addWidget(history_title)
        self.history_table = table(["تاریخ", "شمارهٔ سند", "وضعیت سند", "نرخ‌ها"])
        self.history_table.setMaximumHeight(160)
        layout.addWidget(self.history_table)
        self.undo_button = _btn("برگرداندن تسعیر انتخاب‌شده (فقط پیش از قطعی‌شدن سند)", "↩️")
        self.undo_button.clicked.connect(self.undo)
        layout.addWidget(self.undo_button)
        self.date_field.editingFinished.connect(lambda: self.load_preview(use_table_rates=False))

    def refresh(self) -> None:
        if company_id() is None:
            return
        accounts = [(f"{a.full_code} — {a.name}", a.account_id) for a in coa_service.list_postable_accounts(company_id())]
        gain, loss = fx_service.get_accounts(company_id())
        for box, value in ((self.gain_combo, gain), (self.loss_combo, loss)):
            box.clear()
            box.addItem("— انتخاب —", None)
            for label, account_id in accounts:
                box.addItem(P(label), account_id)
            set_combo(box, value)
        self.load_preview(use_table_rates=False)
        self.load_history()

    def _table_rates(self) -> dict[int, decimal.Decimal]:
        rates = {}
        for row in range(self.rates_table.rowCount()):
            currency_id = self.rates_table.item(row, 0).data(Qt.UserRole)
            item = self.rates_table.item(row, 1)
            value = dec(item.text()) if item else decimal.Decimal(0)
            if value > 0:
                rates[currency_id] = value
        return rates

    def load_preview(self, use_table_rates: bool = True) -> None:
        try:
            self.info = fx_service.preview(company_id(), self.date_field.date(), self._table_rates() if use_table_rates else None)
        except ValueError as exc:
            self.info = None
            fill(self.table, [])
            theme.set_status_label(self.summary_label, str(exc), ok=False)
            return
        currencies = {}
        for row in self.info.rows:
            currencies.setdefault(row.currency_id, (row.currency_code, row.rate))
        fill(self.rates_table, [[code, ""] for code, _rate in currencies.values()], list(currencies))
        for index, (_code, rate) in enumerate(currencies.values()):
            self.rates_table.setItem(index, 1, QTableWidgetItem(P(numerals.format_amount(rate)) if rate else ""))
        for index in range(self.rates_table.rowCount()):
            item = self.rates_table.item(index, 0)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        fill(self.table, [["", r.account_label, r.details_label, r.currency_code, money(r.fc_balance), r.base_before,
                           money(r.rate) if r.rate else "—", r.base_after if r.base_after is not None else "—",
                           r.difference if r.difference is not None else "—"] for r in self.info.rows],
             [r.account_id for r in self.info.rows])
        for index in range(self.table.rowCount()):
            item = self.table.item(index, 0)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
        lines = [f"سود تسعیر: {money(self.info.gain)} — زیان تسعیر: {money(self.info.loss)}"]
        lines += [f"• {p}" for p in self.info.problems]
        if not self.info.rows:
            lines = ["در این تاریخ ماندهٔ ارزی روی حساب‌های دائم نیست."]
        theme.set_status_label(self.summary_label, "\n".join(lines), ok=not self.info.problems)

    def _selected_accounts(self) -> set[int]:
        return {self.table.item(i, 0).data(Qt.UserRole) for i in range(self.table.rowCount())
                if self.table.item(i, 0).checkState() == Qt.Checked}

    def run(self) -> None:
        try:
            fx_service.save_accounts(company_id(), self.gain_combo.currentData(), self.loss_combo.currentData())
            self.load_preview()
            if QMessageBox.question(self, "تسعیر ارز", "سند تسعیر با نرخ‌های جدول ثبت شود؟",
                                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
            entry_id = fx_service.run(company_id(), self.date_field.date(), user_id(), self._table_rates(),
                                      self._selected_accounts())
        except ValueError as exc:
            QMessageBox.warning(self, "تسعیر ارز", str(exc))
            return
        QMessageBox.information(self, "تسعیر ارز", "سند تسعیر «موقت» ثبت شد." if entry_id else "تفاوتی برای ثبت نبود.")
        self.load_preview()
        self.load_history()

    def load_history(self) -> None:
        self.history = fx_service.list_revaluations(company_id())
        codes = {}
        if self.info:
            codes = {r.currency_id: r.currency_code for r in self.info.rows}
        fill(self.history_table, [[h.revaluation_date, h.temporary_no, _STATUS.get(h.status_code, h.status_code),
                                   "، ".join(f"{codes.get(int(k), k)}: {numerals.format_amount(decimal.Decimal(v))}"
                                            for k, v in h.rates.items())] for h in self.history],
             [h.revaluation_id for h in self.history])

    def undo(self) -> None:
        rows = sorted({item.row() for item in self.history_table.selectedItems()})
        if not rows:
            QMessageBox.information(self, "برگرداندن تسعیر", "یک تسعیر را از فهرست انتخاب کنید.")
            return
        if QMessageBox.question(self, "برگرداندن تسعیر", "سند این تسعیر حذف شود؟",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            fx_service.undo(self.history[rows[0]].revaluation_id, company_id())
        except ValueError as exc:
            QMessageBox.warning(self, "برگرداندن تسعیر", str(exc))
            return
        self.load_preview()
        self.load_history()
