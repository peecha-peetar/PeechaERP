"""R379: قفل پرداخت تطبیق سه‌طرفه — حد مجاز، فاکتورهای خرید با پرداخت بسته و آزادسازی با دلیل."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from peecha.services import three_way_lock as twl
from peecha.ui import theme
from peecha.ui.screens.fixed_assets import P, company_id, dec, fill, selected_data, table, user_id
from peecha.ui.widgets import FieldGrid, FieldSpec, build_page_header


def _btn(label: str, glyph: str, kind: str = "") -> QPushButton:
    button = QPushButton(glyph)
    button.setToolTip(label)
    button.setAccessibleName(label)
    button.setObjectName({"primary": "primaryIconButton", "danger": "dangerIconButton"}.get(kind, "iconButton"))
    button.setFixedWidth(48 if kind == "primary" else 44)
    button.setCursor(Qt.PointingHandCursor)
    return button


class PurchaseThreeWayLockScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.rows: list[twl.BlockedInvoice] = []
        self.ask_reason = None  # برای آزمون
        layout = QVBoxLayout(self)
        layout.addWidget(build_page_header(
            "قفل پرداخت تطبیق سه‌طرفه", "فاکتور خریدی که از سفارش ساخته شده و مقدارش بیش از رسید انبار یا سفارش است یا فی‌اش "
            "بیش از حد مجاز با سفارش فرق دارد، تا رفع مغایرت یا آزادسازی با ذکر دلیل پرداخت و تسویه نمی‌شود. این قفل با کلید "
            "«قفل پرداخت فاکتور خرید با تطبیق سه‌طرفه» در قابلیت‌های فعال روشن می‌شود."))
        self.state_label = QLabel("")
        self.state_label.setWordWrap(True)
        layout.addWidget(self.state_label)
        row = QHBoxLayout()
        self.price_field, self.qty_field = QLineEdit(), QLineEdit()
        row.addWidget(FieldGrid([FieldSpec("twl_price", "حد مجاز اختلاف فی (درصد)", self.price_field, span=1),
                                 FieldSpec("twl_qty", "حد مجاز اضافهٔ مقدار (درصد)", self.qty_field, span=1)]), 1)
        save = _btn("ذخیرهٔ حد مجاز", "💾", "primary")
        save.clicked.connect(self.save_settings)
        row.addWidget(save)
        layout.addLayout(row)
        bar = QHBoxLayout()
        self.released_box = QCheckBox("نمایش فاکتورهای آزادشده")
        self.released_box.toggled.connect(self.refresh)
        bar.addWidget(self.released_box)
        bar.addStretch(1)
        for label, glyph, kind, slot in (("آزادسازی پرداخت فاکتور انتخاب‌شده با ذکر دلیل", "✅", "", self.release),
                                         ("به‌روزرسانی", "🔄", "", self.refresh)):
            button = _btn(label, glyph, kind)
            button.clicked.connect(slot)
            bar.addWidget(button)
        layout.addLayout(bar)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.table = table(["شمارهٔ فاکتور", "تاریخ", "تامین‌کننده", "مبلغ", "مغایرت‌ها", "وضعیت پرداخت", "دلیل آزادسازی"])
        layout.addWidget(self.table, 1)

    def refresh(self) -> None:
        cid = company_id()
        if cid is None:
            return
        on = twl.enabled(cid)
        self.state_label.setText("قفل روشن است؛ پرداخت فاکتورهای زیر بسته است." if on else
                                 "قفل خاموش است و پرداخت هیچ فاکتوری بسته نمی‌شود؛ فهرست زیر فقط مغایرت‌ها را نشان می‌دهد.")
        price, qty = twl.get_settings(cid)
        self.price_field.setText(P(f"{price.normalize():f}"))
        self.qty_field.setText(P(f"{qty.normalize():f}"))
        self.rows = twl.list_invoices(cid, include_released=self.released_box.isChecked())
        fill(self.table, [[r.document_no, r.document_date, r.supplier, r.total_amount,
                           "؛ ".join(f"{i.item_label}: {i.text}" for i in r.issues),
                           "آزاد" if r.released else ("بسته" if on else "—"), r.release_reason] for r in self.rows],
             [r.document_id for r in self.rows])

    def _status(self, text: str, ok: bool) -> None:
        theme.set_status_label(self.status_label, text, ok=ok)

    def save_settings(self) -> bool:
        try:
            twl.save_settings(company_id(), user_id(), dec(self.price_field.text()), dec(self.qty_field.text()))
        except (ValueError, decimal.InvalidOperation) as exc:
            self._status(str(exc) if isinstance(exc, ValueError) else "درصد نامعتبر است.", False)
            return False
        self.refresh()
        self._status("حد مجاز ذخیره شد.", True)
        return True

    def release(self) -> bool:
        doc_id = selected_data(self.table)
        if doc_id is None:
            self._status("یک فاکتور را انتخاب کنید.", False)
            return False
        if self.ask_reason is not None:
            reason, ok = self.ask_reason(), True
        else:
            reason, ok = QInputDialog.getText(self, "آزادسازی پرداخت", "دلیل آزادسازی:")
        if not ok:
            return False
        try:
            twl.release(company_id(), user_id(), doc_id, reason)
        except ValueError as exc:
            self._status(str(exc), False)
            return False
        self.refresh()
        self._status("پرداخت فاکتور آزاد شد.", True)
        return True
