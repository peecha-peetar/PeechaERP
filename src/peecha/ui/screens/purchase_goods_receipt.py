"""تاییدِ رسیدِ کالا -- طبقِ گزارشِ صریحِ کاربر: «بعدِ تاییدِ سفارشِ خرید
انباردار کجا باید رسیدنِ کالا را تایید کند؟ و دسترسی هم نداشته باشد
قیمتِ کالا را ببیند -- و این تنظیمی باشد.»

هم‌الگو با pre_sales_fulfillment.py (همان زیرساختِ warehouse_approved_at/
warehouse_delivered_quantیِ ازپیش‌موجود)، با دو تفاوتِ عمده:
۱) این‌جا برایِ PURCHASE_ORDER است، نه SALES_ORDERِ کانالِ پخشِ سرد --
   و فقط وقتی Toggleِ PURCHASE_ORDER_GOODS_RECEIPT (تنظیماتِ بازرگانی)
   برایِ شرکت روشن باشد چیزی نشان می‌دهد.
۲) جدولِ ردیف‌ها عمداً هیچ ستونِ قیمتی ندارد -- و چون این یک آیتمِ
   ناوبریِ مستقل است (نه تبی درونِ فرمِ کاملِ سفارشِ خرید)، می‌توان به
   نقشِ انباردار فقط دسترسیِ همین فرم را داد، نه فرمِ سفارشِ خرید که
   قیمت دارد؛ یعنی «پنهان‌کردنِ قیمت» از طریقِ همان مدلِ استانداردِ
   دسترسیِ فرم‌ها (roles.py) انجام می‌شود، نه یک مکانیزمِ تازه.
۳) بدونِ مفهومِ توزین (آن فقط برایِ کالایِ وزنیِ فروشِ حضوری معنا دارد).
"""

from __future__ import annotations

import decimal

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session as app_session
from peecha.services import commercial_documents as documents_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.ui.screens.journal_entry import _AmountField
from peecha.ui.widgets import FieldHelpMixin

_COLUMNS = ["شماره", "تاریخ", "تامین‌کننده", "وضعیت", "عملیات"]
_LINE_COLUMNS = ["کالا", "واحد", "مقدارِ سفارش", "مقدارِ دریافتی"]


def _status_label(doc) -> str:
    if doc.warehouse_approved_at is None:
        return "در انتظارِ تاییدِ رسید"
    return "رسید تایید شده -- آمادهٔ تبدیل به فاکتور"


class _GoodsReceiptDialog(QDialog):
    def __init__(self, parent: QWidget, document_id: int, company_id: int) -> None:
        super().__init__(parent)
        self.setWindowTitle("بازکردنِ سفارش -- تاییدِ رسیدِ کالا")
        self.setMinimumWidth(560)
        self._document_id = document_id
        self._company_id = company_id
        self._qty_fields: dict[int, _AmountField] = {}
        self.changed = False

        layout = QVBoxLayout(self)
        self.header_label = QLabel("")
        self.header_label.setWordWrap(True)
        layout.addWidget(self.header_label)

        hint = QLabel(
            "مقدارِ واقعاً دریافت‌شدهٔ هر ردیف را وارد/ویرایش کنید -- اگر خالی/برابرِ مقدارِ سفارش بماند، "
            "همان مقدارِ سفارش به‌عنوانِ مقدارِ دریافتی لحاظ می‌شود."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.lines_table = QTableWidget(0, len(_LINE_COLUMNS))
        self.lines_table.setHorizontalHeaderLabels(_LINE_COLUMNS)
        self.lines_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lines_table.verticalHeader().setVisible(False)
        self.lines_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.lines_table)

        self.save_button = QPushButton("💾 ذخیرهٔ مقادیرِ دریافتی")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save_quantities)
        layout.addWidget(self.save_button)

        self.receipt_button = QPushButton("")
        self.receipt_button.clicked.connect(self._toggle_receipt)
        layout.addWidget(self.receipt_button)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        layout.addWidget(buttons)

        self._reload()

    def _reload(self) -> None:
        self.status_label.setText("")
        try:
            doc, lines = documents_service.get_document(self._document_id, self._company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._doc = doc
        converted = documents_service.document_has_been_converted(self._document_id, self._company_id)

        self.header_label.setText(
            f"سفارشِ خریدِ شماره‌یِ {numerals.to_persian_digits(str(doc.document_no))} -- "
            f"{dimensions_service.get_detail_account_label(doc.counterparty_detail_account_id)} -- "
            f"{numerals.format_jalali_date(doc.document_date)}"
        )

        items_by_id = {it.item_id: it for it in catalog_service.list_items(self._company_id)}
        uom_decimal_places = {u.uom_id: u.decimal_places for u in catalog_service.list_uoms(self._company_id)}
        self._qty_fields = {}
        self.lines_table.setRowCount(len(lines))
        for row_index, ln in enumerate(lines):
            item = items_by_id.get(ln.item_id)
            dp = uom_decimal_places.get(item.base_uom_id, 3) if item else 3
            self.lines_table.setItem(row_index, 0, QTableWidgetItem(f"{item.code} — {item.name or ''}" if item else str(ln.item_id)))
            self.lines_table.setItem(row_index, 1, QTableWidgetItem(item.base_uom_code if item else ""))
            self.lines_table.setItem(row_index, 2, QTableWidgetItem(numerals.format_money(ln.quantity, dp)))
            qty_field = _AmountField()
            qty_field.setDecimals(dp)
            qty_field.setValue(float(ln.warehouse_delivered_quantity if ln.warehouse_delivered_quantity is not None else ln.quantity))
            qty_field.setEnabled(not converted)
            self._qty_fields[ln.line_id] = qty_field
            self.lines_table.setCellWidget(row_index, 3, qty_field)
        self.lines_table.resizeRowsToContents()

        self.save_button.setEnabled(not converted)

        if converted:
            self.receipt_button.setText("✅ تاییدِ رسید (قطعی -- به فاکتور تبدیل شده)")
            self.receipt_button.setEnabled(False)
            return

        if doc.warehouse_approved_at is None:
            self.receipt_button.setText("✅ تاییدِ رسیدِ کالا")
            self.receipt_button.setObjectName("primaryButton")
        else:
            self.receipt_button.setText("↩️ بازگشتِ تاییدِ رسید")
            self.receipt_button.setObjectName("dangerButton")
        self.receipt_button.setEnabled(True)
        self.receipt_button.setStyleSheet("")
        self.receipt_button.style().unpolish(self.receipt_button)
        self.receipt_button.style().polish(self.receipt_button)

    def _save_quantities(self) -> None:
        quantities = {line_id: decimal.Decimal(str(field.value())) for line_id, field in self._qty_fields.items()}
        try:
            documents_service.set_warehouse_delivered_quantities(self._document_id, self._company_id, quantities)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.changed = True
        self._reload()

    def _toggle_receipt(self) -> None:
        user_id = app_session.current_user.user_id
        try:
            if self._doc.warehouse_approved_at is None:
                documents_service.approve_warehouse(self._document_id, self._company_id, user_id)
            else:
                documents_service.revert_warehouse_approval(self._document_id, self._company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.changed = True
        self._reload()


class PurchaseGoodsReceiptScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._queue: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(14)

        title = QLabel("تاییدِ رسیدِ کالا -- سفارش‌هایِ خرید")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        hint = QLabel(
            "فقط سفارش‌هایِ خریدِ تاییدشده/تصویب‌شده‌ای که هنوز به فاکتور تبدیل نشده‌اند این‌جا می‌آیند -- "
            "بدونِ قیمت، فقط مقدار. با «📂 بازکردن» مقدارِ واقعیِ دریافتیِ هر ردیف را ثبت و رسید را تایید کنید."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setMinimumHeight(300)
        layout.addWidget(self.table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.set_field_help([
            (self.table, "سفارش‌هایِ خریدِ تاییدشده/تصویب‌شده‌ای که هنوز به فاکتور تبدیل نشده‌اند -- با «بازکردن»، مقدارِ دریافتی و تاییدِ رسید انجام می‌شود."),
        ])

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self.status_label.setText("")
        self._queue = documents_service.list_purchase_order_goods_receipt_queue(company_id)
        if not self._queue:
            self.status_label.setObjectName("sectionHint")
            self.status_label.setText(
                "موردی نیست -- یا سفارشِ خریدِ در انتظار وجود ندارد، یا Toggleِ «تاییدِ رسیدِ کالا» "
                "در تنظیماتِ بازرگانی هنوز روشن نشده است."
            )
        self.table.setRowCount(len(self._queue))
        for row_index, doc in enumerate(self._queue):
            values = [
                numerals.to_persian_digits(str(doc.document_no)),
                numerals.format_jalali_date(doc.document_date),
                dimensions_service.get_detail_account_label(doc.counterparty_detail_account_id),
                _status_label(doc),
            ]
            for col_index, value in enumerate(values):
                self.table.setItem(row_index, col_index, QTableWidgetItem(value))
            button = QPushButton("📂 بازکردن")
            button.clicked.connect(lambda _checked=False, document_id=doc.document_id: self._open_document(document_id))
            self.table.setCellWidget(row_index, len(_COLUMNS) - 1, button)
        self.table.resizeRowsToContents()

    def _open_document(self, document_id: int) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        dialog = _GoodsReceiptDialog(self, document_id, company_id)
        dialog.exec()
        if dialog.changed:
            self.refresh()
