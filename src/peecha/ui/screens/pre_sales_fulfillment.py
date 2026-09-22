"""تاییدِ انبار و توزین -- طبقِ درخواستِ صریحِ کاربر (روالِ کاملِ پخشِ سرد):
سفارشِ تصویب‌شده (کانالِ پخشِ سرد) باید پیش از تبدیل به فاکتورِ فروش، هم
تاییدِ انبار بگیرد و هم -- اگر کالایِ توزینی داشت -- تاییدِ توزین.

طبقِ گزارشِ صریحِ بعدیِ کاربر: (۱) انباردار باید بتواند خودِ سفارش را
باز کند و مقدارِ واقعیِ تحویلی (وزنی یا تعدادی) را وارد/ادیت کند --
نه صرفاً یک دکمهٔ «تایید» ساده روی کلِ سفارش. (۲) بعدِ تاییدِ انبار،
سفارش نباید کاملاً غیب شود -- تا وقتی به فاکتور تبدیل نشده (که همان
«تاییدِ نهایی» است)، انباردار باید بتواند تاییدش را برگرداند و دوباره
مقادیر را ویرایش کند. این صفحه حالا یک فهرستِ واحد (نه دو فهرستِ
جداگانه) با وضعیتِ هر سفارش نشان می‌دهد؛ همه‌چیز از طریقِ بازکردنِ خودِ
سفارش (دیالوگِ زیر) انجام می‌شود."""

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
    QMessageBox,
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

_COLUMNS = ["شماره", "تاریخ", "طرفِ‌حساب", "جمعِ کل", "وضعیت", "عملیات"]
_LINE_COLUMNS = ["کالا", "واحد", "مقدارِ سفارش", "مقدارِ تحویلی"]


class _FulfillmentDialog(QDialog):
    def __init__(self, parent: QWidget, document_id: int, company_id: int) -> None:
        super().__init__(parent)
        self.setWindowTitle("بازکردنِ سفارش -- تحویلِ انبار/توزین")
        self.setMinimumWidth(560)
        self._document_id = document_id
        self._company_id = company_id
        self._qty_fields: dict[int, _AmountField] = {}

        layout = QVBoxLayout(self)
        self.header_label = QLabel("")
        self.header_label.setWordWrap(True)
        layout.addWidget(self.header_label)

        self.editable_hint = QLabel(
            "مقدارِ تحویلیِ هر ردیف را وارد/ویرایش کنید -- برایِ کالاهایِ ترازویی همان وزنِ واقعی، "
            "برایِ بقیه همان تعدادِ واقعیِ تحویلی. اگر خالی/برابرِ مقدارِ سفارش بماند، همان مقدارِ سفارش لحاظ می‌شود."
        )
        self.editable_hint.setObjectName("sectionHint")
        self.editable_hint.setWordWrap(True)
        layout.addWidget(self.editable_hint)

        self.lines_table = QTableWidget(0, len(_LINE_COLUMNS))
        self.lines_table.setHorizontalHeaderLabels(_LINE_COLUMNS)
        self.lines_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lines_table.verticalHeader().setVisible(False)
        self.lines_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.lines_table)

        self.save_button = QPushButton("💾 ذخیرهٔ مقادیرِ تحویلی")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save_quantities)
        layout.addWidget(self.save_button)

        approval_row = QHBoxLayout()
        self.warehouse_button = QPushButton("")
        self.warehouse_button.clicked.connect(self._toggle_warehouse)
        approval_row.addWidget(self.warehouse_button)
        self.weighing_button = QPushButton("")
        self.weighing_button.clicked.connect(self._toggle_weighing)
        approval_row.addWidget(self.weighing_button)
        layout.addLayout(approval_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        layout.addWidget(buttons)

        self.changed = False
        self._reload()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    def _reload(self) -> None:
        self.status_label.setText("")
        try:
            doc, lines = documents_service.get_document(self._document_id, self._company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._doc = doc
        self._lines = lines
        converted = documents_service.document_has_been_converted(self._document_id, self._company_id)
        requires_weighing = documents_service.document_requires_weighing(self._document_id, self._company_id)

        self.header_label.setText(
            f"سفارشِ شماره‌یِ {numerals.to_persian_digits(str(doc.document_no))} -- "
            f"{dimensions_service.get_detail_account_label(doc.counterparty_detail_account_id)} -- "
            f"{numerals.format_jalali_date(doc.document_date)}"
        )

        items_by_id = {it.item_id: it for it in catalog_service.list_items(self._company_id)}
        self._qty_fields = {}
        self.lines_table.setRowCount(len(lines))
        for row_index, ln in enumerate(lines):
            item = items_by_id.get(ln.item_id)
            self.lines_table.setItem(row_index, 0, QTableWidgetItem(f"{item.code} — {item.name or ''}" if item else str(ln.item_id)))
            self.lines_table.setItem(row_index, 1, QTableWidgetItem(item.base_uom_code if item else ""))
            self.lines_table.setItem(row_index, 2, QTableWidgetItem(numerals.format_money(ln.quantity, 3)))
            qty_field = _AmountField()
            qty_field.setDecimals(3)
            qty_field.setValue(float(ln.warehouse_delivered_quantity if ln.warehouse_delivered_quantity is not None else ln.quantity))
            qty_field.setEnabled(not converted)
            self._qty_fields[ln.line_id] = qty_field
            self.lines_table.setCellWidget(row_index, 3, qty_field)
        self.lines_table.resizeRowsToContents()

        self.save_button.setEnabled(not converted)

        if converted:
            self.warehouse_button.setText("✅ تاییدِ انبار (قطعی -- به فاکتور تبدیل شده)")
            self.warehouse_button.setEnabled(False)
            self.weighing_button.setText("✅ تاییدِ توزین (قطعی -- به فاکتور تبدیل شده)")
            self.weighing_button.setEnabled(False)
            self.weighing_button.setVisible(requires_weighing)
            return

        if doc.warehouse_approved_at is None:
            self.warehouse_button.setText("✅ تاییدِ انبار")
            self.warehouse_button.setObjectName("primaryButton")
        else:
            self.warehouse_button.setText("↩️ بازگشتِ تاییدِ انبار")
            self.warehouse_button.setObjectName("dangerButton")
        self.warehouse_button.setStyleSheet("")
        self.warehouse_button.style().unpolish(self.warehouse_button)
        self.warehouse_button.style().polish(self.warehouse_button)

        self.weighing_button.setVisible(requires_weighing)
        if requires_weighing:
            if doc.warehouse_approved_at is None:
                self.weighing_button.setText("✅ تاییدِ توزین (ابتدا انبار را تایید کنید)")
                self.weighing_button.setEnabled(False)
            elif doc.weighing_approved_at is None:
                self.weighing_button.setText("✅ تاییدِ توزین")
                self.weighing_button.setObjectName("primaryButton")
                self.weighing_button.setEnabled(True)
            else:
                self.weighing_button.setText("↩️ بازگشتِ تاییدِ توزین")
                self.weighing_button.setObjectName("dangerButton")
                self.weighing_button.setEnabled(True)
            self.weighing_button.setStyleSheet("")
            self.weighing_button.style().unpolish(self.weighing_button)
            self.weighing_button.style().polish(self.weighing_button)

    def _save_quantities(self) -> None:
        quantities = {line_id: decimal.Decimal(str(field.value())) for line_id, field in self._qty_fields.items()}
        try:
            documents_service.set_warehouse_delivered_quantities(self._document_id, self._company_id, quantities)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.changed = True
        self._reload()

    def _toggle_warehouse(self) -> None:
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

    def _toggle_weighing(self) -> None:
        user_id = app_session.current_user.user_id
        try:
            if self._doc.weighing_approved_at is None:
                documents_service.approve_weighing(self._document_id, self._company_id, user_id)
            else:
                documents_service.revert_weighing_approval(self._document_id, self._company_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.changed = True
        self._reload()


class PreSalesFulfillmentScreen(FieldHelpMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._queue: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(14)

        title = QLabel("تاییدِ انبار و توزین -- سفارش‌هایِ پخشِ سرد")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        hint = QLabel(
            "فقط سفارش‌هایِ تصویب‌شده‌یِ کانالِ «پخشِ سرد» که هنوز به فاکتور تبدیل نشده‌اند این‌جا می‌آیند. "
            "با «📂 بازکردن» می‌توانید مقدارِ واقعیِ تحویلی/توزین‌شدهٔ هر ردیف را وارد کنید و تاییدِ انبار/توزین را "
            "بزنید یا (تا پیش از تبدیل به فاکتور) برگردانید."
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
            (self.table, "سفارش‌هایِ پخشِ سردِ تصویب‌شده‌ای که هنوز به فاکتور تبدیل نشده‌اند -- با «بازکردن»، مقدارِ تحویلی و تاییدِ انبار/توزین انجام می‌شود."),
        ])

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self.status_label.setText("")
        self._queue = documents_service.list_pre_sales_fulfillment_queue(company_id)
        self.table.setRowCount(len(self._queue))
        for row_index, doc in enumerate(self._queue):
            values = [
                numerals.to_persian_digits(str(doc.document_no)),
                numerals.format_jalali_date(doc.document_date),
                dimensions_service.get_detail_account_label(doc.counterparty_detail_account_id),
                numerals.format_money(doc.total_amount, 0),
                documents_service.describe_pre_sales_fulfillment_status(doc.document_id, company_id) or "",
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
        dialog = _FulfillmentDialog(self, document_id, company_id)
        dialog.exec()
        if dialog.changed:
            self.refresh()
