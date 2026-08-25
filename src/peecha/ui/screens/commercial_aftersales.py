"""خدماتِ پس‌ازفروش و گارانتی (مرحلهٔ ۹) — گارانتیِ سریالی، تیکتِ خدماتی،
و RMA به‌عنوانِ دروازهٔ پیشِ‌از برگشتِ فروش."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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

from peecha import session as app_session
from peecha.services import commercial_aftersales as aftersales_service
from peecha.services import commercial_documents as documents_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.services import inventory_locations as locations_service
from peecha.ui.widgets import FieldGrid, FieldSpec, LayoutEditMixin, wrap_scrollable

_WARRANTY_STATUS_LABELS = {"ACTIVE": "معتبر", "EXPIRED": "منقضی", "VOIDED": "باطل‌شده"}
_TICKET_STATUS_LABELS = {"OPEN": "باز", "IN_PROGRESS": "درحالِ انجام", "RESOLVED": "حل‌شده", "CLOSED": "بسته"}
_TICKET_STATUS_ORDER = ("OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED")
_RMA_STATUS_LABELS = {"REQUESTED": "درخواست‌شده", "APPROVED": "تاییدشده", "REJECTED": "ردشده", "COMPLETED": "تکمیل‌شده"}
_RMA_REASON_LABELS = {"DEFECTIVE": "معیوب", "WRONG_ITEM": "کالایِ اشتباه", "NOT_SATISFIED": "عدمِ رضایت", "DAMAGED_IN_TRANSIT": "آسیب‌دیده در حمل"}


class _TabLayoutController(LayoutEditMixin):
    """کنترلرِ سبکِ ویرایشِ‌چیدمانِ مستقل برایِ هر تب — چون LayoutEditMixin
    وضعیتِ screen_code/grids را رویِ self نگه می‌دارد (نه هر گرید
    به‌تنهایی)، و این صفحه دو تبِ مستقل (تیکت/RMA) با دو کدِ صفحهٔ جدا
    دارد، هر تب کنترلرِ خودش را می‌گیرد تا ذخیره/بازنشانیِ چیدمانِ یک تب
    رویِ دیگری اثر نگذارد."""


class CommercialAftersalesScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._items: list[catalog_service.ItemRow] = []
        self._customers: list[dict] = []
        self._invoice_lines: list = []
        self._selected_ticket_id: int | None = None
        self._selected_rma_id: int | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("خدماتِ پس‌ازفروش و گارانتی")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._build_warranty_tab(), "گارانتی")
        tabs.addTab(self._build_ticket_tab(), "تیکتِ خدماتی")
        tabs.addTab(self._build_rma_tab(), "RMA (برگشتِ کالا)")
        outer.addWidget(tabs, stretch=1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    # --- گارانتی -----------------------------------------------------------
    def _build_warranty_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)

        self.warranty_table = QTableWidget(0, 5)
        self.warranty_table.setHorizontalHeaderLabels(["کالا", "تاریخِ شروع", "تاریخِ پایان", "وضعیت", ""])
        self.warranty_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.warranty_table.verticalHeader().setVisible(False)
        self.warranty_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        outer.addWidget(self.warranty_table, stretch=1)

        form = QHBoxLayout()
        self.warranty_invoice_combo = QComboBox()
        self.warranty_invoice_combo.currentIndexChanged.connect(self._on_warranty_invoice_selected)
        form.addWidget(self.warranty_invoice_combo, stretch=2)
        self.warranty_line_combo = QComboBox()
        form.addWidget(self.warranty_line_combo, stretch=2)
        self.warranty_duration_field = QSpinBox()
        self.warranty_duration_field.setRange(1, 240)
        self.warranty_duration_field.setValue(12)
        self.warranty_duration_field.setSuffix(" ماه")
        form.addWidget(self.warranty_duration_field)
        self.warranty_terms_field = QLineEdit()
        self.warranty_terms_field.setPlaceholderText("شرایطِ گارانتی (اختیاری)")
        form.addWidget(self.warranty_terms_field, stretch=2)
        add_warranty_button = QPushButton("🛡️")
        add_warranty_button.setObjectName("primaryIconButton")
        add_warranty_button.setFixedWidth(48)
        add_warranty_button.setToolTip("صدورِ گارانتی")
        add_warranty_button.clicked.connect(self._add_warranty)
        form.addWidget(add_warranty_button)
        outer.addLayout(form)

        self.warranty_status_label = QLabel("")
        self.warranty_status_label.setObjectName("statusError")
        outer.addWidget(self.warranty_status_label)
        return wrap_scrollable(page)

    def _on_warranty_invoice_selected(self) -> None:
        self.warranty_line_combo.clear()
        document_id = self.warranty_invoice_combo.currentData()
        company_id = self._company_id()
        if document_id is None or company_id is None:
            return
        items_by_id = {it.item_id: it for it in self._items}
        _doc, lines = documents_service.get_document(document_id, company_id)
        self._invoice_lines = lines
        for line in lines:
            item = items_by_id.get(line.item_id)
            label = f"{item.code} — {item.name or ''} (تعداد: {line.quantity})" if item else f"ردیف {line.line_no}"
            self.warranty_line_combo.addItem(label, line.line_id)

    def _add_warranty(self) -> None:
        line_id = self.warranty_line_combo.currentData()
        if line_id is None:
            self.warranty_status_label.setText("ابتدا یک فاکتورِ فروش و ردیفِ آن را انتخاب کنید.")
            return
        line = next((l for l in self._invoice_lines if l.line_id == line_id), None)
        if line is None:
            return
        try:
            aftersales_service.create_warranty(
                line_id, line.item_id, self.warranty_duration_field.value(),
                terms=self.warranty_terms_field.text().strip() or None, serial_id=line.serial_id,
            )
        except ValueError as exc:
            self.warranty_status_label.setText(str(exc))
            return
        self.warranty_terms_field.clear()
        self.warranty_status_label.setText("")
        self.refresh()

    def _refresh_warranties(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        items_by_id = {it.item_id: it for it in self._items}
        warranties = aftersales_service.list_warranties(company_id)
        self.warranty_table.setRowCount(len(warranties))
        for row_index, w in enumerate(warranties):
            item = items_by_id.get(w.item_id)
            status = aftersales_service.get_effective_warranty_status(w.warranty_id)
            self.warranty_table.setItem(row_index, 0, QTableWidgetItem(f"{item.code} — {item.name or ''}" if item else str(w.item_id)))
            self.warranty_table.setItem(row_index, 1, QTableWidgetItem(str(w.start_date)))
            self.warranty_table.setItem(row_index, 2, QTableWidgetItem(str(w.end_date)))
            self.warranty_table.setItem(row_index, 3, QTableWidgetItem(_WARRANTY_STATUS_LABELS.get(status, status)))
            void_button = QPushButton("🚫")
            void_button.setObjectName("iconButton")
            void_button.setFixedWidth(44)
            void_button.setToolTip("ابطال")
            void_button.setEnabled(status == "ACTIVE")
            void_button.clicked.connect(lambda _checked=False, wid=w.warranty_id: self._void_warranty(wid))
            self.warranty_table.setCellWidget(row_index, 4, void_button)

    def _void_warranty(self, warranty_id: int) -> None:
        aftersales_service.void_warranty(warranty_id, "ابطال از طریقِ فرم")
        self.refresh()

    # --- تیکتِ خدماتی --------------------------------------------------------
    def _build_ticket_tab(self) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)

        left = QVBoxLayout()
        self.ticket_table = QTableWidget(0, 4)
        self.ticket_table.setHorizontalHeaderLabels(["موضوع", "مشتری", "وضعیت", "هزینه‌بردار"])
        self.ticket_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.ticket_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.ticket_table.verticalHeader().setVisible(False)
        self.ticket_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.ticket_table.cellClicked.connect(self._on_ticket_selected)
        left.addWidget(self.ticket_table, stretch=1)

        self.ticket_customer_combo = QComboBox()
        self.ticket_subject_field = QLineEdit()
        self.ticket_subject_field.setPlaceholderText("موضوعِ تیکت")
        self.ticket_item_combo = QComboBox()
        self.ticket_item_combo.addItem("(بدونِ کالایِ مشخص)", None)
        self.ticket_warranty_combo = QComboBox()
        self.ticket_warranty_combo.addItem("(بدونِ گارانتی)", None)
        self.ticket_description_field = QLineEdit()
        self.ticket_description_field.setPlaceholderText("توضیحات (اختیاری)")
        self.ticket_form_grid = FieldGrid([
            FieldSpec("customer", "مشتری", self.ticket_customer_combo, span=2),
            FieldSpec("subject", "موضوعِ تیکت", self.ticket_subject_field, span=3),
            FieldSpec("item", "کالا", self.ticket_item_combo, span=2),
            FieldSpec("warranty", "گارانتی", self.ticket_warranty_combo, span=2),
            FieldSpec("description", "توضیحات", self.ticket_description_field, span=3),
        ])
        self._ticket_layout_controller = _TabLayoutController()
        self._ticket_layout_controller.register_field_grids("commercial_aftersales_ticket", [self.ticket_form_grid])
        ticket_form = QVBoxLayout()
        ticket_form.addWidget(self.ticket_form_grid)
        add_ticket_button = QPushButton("🎫")
        add_ticket_button.setObjectName("primaryIconButton")
        add_ticket_button.setFixedWidth(48)
        add_ticket_button.setToolTip("تیکتِ تازه")
        add_ticket_button.clicked.connect(self._add_ticket)
        ticket_form.addWidget(add_ticket_button)
        left.addLayout(ticket_form)
        outer.addLayout(left, stretch=2)

        right = QVBoxLayout()
        right.addWidget(QLabel("تغییرِ وضعیتِ تیکتِ انتخاب‌شده"))
        status_row = QHBoxLayout()
        self.ticket_status_combo = QComboBox()
        for code in _TICKET_STATUS_ORDER:
            self.ticket_status_combo.addItem(_TICKET_STATUS_LABELS[code], code)
        status_row.addWidget(self.ticket_status_combo)
        apply_status_button = QPushButton("✔️")
        apply_status_button.setObjectName("iconButton")
        apply_status_button.setFixedWidth(44)
        apply_status_button.setToolTip("اعمال")
        apply_status_button.clicked.connect(self._apply_ticket_status)
        status_row.addWidget(apply_status_button)
        right.addLayout(status_row)

        right.addWidget(QLabel("فاکتورِ تسویهٔ تیکتِ هزینه‌بردار"))
        invoice_row = QHBoxLayout()
        self.ticket_invoice_combo = QComboBox()
        invoice_row.addWidget(self.ticket_invoice_combo, stretch=1)
        link_invoice_button = QPushButton("🔗")
        link_invoice_button.setObjectName("iconButton")
        link_invoice_button.setFixedWidth(44)
        link_invoice_button.setToolTip("پیوند")
        link_invoice_button.clicked.connect(self._link_ticket_invoice)
        invoice_row.addWidget(link_invoice_button)
        right.addLayout(invoice_row)

        right.addWidget(QLabel("قطعاتِ مصرف‌شده"))
        self.ticket_parts_table = QTableWidget(0, 2)
        self.ticket_parts_table.setHorizontalHeaderLabels(["کالا", "مقدار"])
        self.ticket_parts_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.ticket_parts_table.verticalHeader().setVisible(False)
        self.ticket_parts_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.ticket_parts_table.setMaximumHeight(120)
        right.addWidget(self.ticket_parts_table)
        part_form = QHBoxLayout()
        self.ticket_part_item_combo = QComboBox()
        part_form.addWidget(self.ticket_part_item_combo, stretch=1)
        self.ticket_part_qty_field = QLineEdit()
        self.ticket_part_qty_field.setPlaceholderText("مقدار")
        self.ticket_part_qty_field.setMaximumWidth(80)
        part_form.addWidget(self.ticket_part_qty_field)
        add_part_button = QPushButton("📦")
        add_part_button.setObjectName("iconButton")
        add_part_button.setFixedWidth(44)
        add_part_button.setToolTip("ثبتِ مصرف")
        add_part_button.clicked.connect(self._add_part_used)
        part_form.addWidget(add_part_button)
        right.addLayout(part_form)

        self.ticket_status_label = QLabel("")
        self.ticket_status_label.setObjectName("statusError")
        right.addWidget(self.ticket_status_label)
        right.addStretch(1)
        outer.addLayout(right, stretch=2)
        return wrap_scrollable(page)

    def _add_ticket(self) -> None:
        company_id = self._company_id()
        customer_id = self.ticket_customer_combo.currentData()
        subject = self.ticket_subject_field.text().strip()
        if company_id is None or customer_id is None or not subject:
            self.ticket_status_label.setText("مشتری و موضوع را وارد کنید.")
            return
        try:
            aftersales_service.open_ticket(
                customer_id, subject, warranty_id=self.ticket_warranty_combo.currentData(),
                item_id=self.ticket_item_combo.currentData(), description=self.ticket_description_field.text().strip() or None,
            )
        except ValueError as exc:
            self.ticket_status_label.setText(str(exc))
            return
        self.ticket_subject_field.clear()
        self.ticket_description_field.clear()
        self.ticket_status_label.setText("")
        self.refresh()

    def _on_ticket_selected(self, row: int, _column: int) -> None:
        self._selected_ticket_id = self.ticket_table.item(row, 0).data(Qt.UserRole)
        self._refresh_ticket_parts()

    def _refresh_ticket_parts(self) -> None:
        self.ticket_parts_table.setRowCount(0)
        if self._selected_ticket_id is None:
            return
        items_by_id = {it.item_id: it for it in self._items}
        parts = aftersales_service.list_service_ticket_parts_used(self._selected_ticket_id)
        self.ticket_parts_table.setRowCount(len(parts))
        for row_index, p in enumerate(parts):
            item = items_by_id.get(p.item_id)
            self.ticket_parts_table.setItem(row_index, 0, QTableWidgetItem(f"{item.code} — {item.name or ''}" if item else str(p.item_id)))
            self.ticket_parts_table.setItem(row_index, 1, QTableWidgetItem(str(p.quantity)))

    def _apply_ticket_status(self) -> None:
        if self._selected_ticket_id is None:
            self.ticket_status_label.setText("ابتدا یک تیکت را از فهرست انتخاب کنید.")
            return
        try:
            aftersales_service.advance_ticket_status(self._selected_ticket_id, self.ticket_status_combo.currentData())
        except ValueError as exc:
            self.ticket_status_label.setText(str(exc))
            return
        self.ticket_status_label.setText("")
        self.refresh()

    def _link_ticket_invoice(self) -> None:
        invoice_id = self.ticket_invoice_combo.currentData()
        if self._selected_ticket_id is None or invoice_id is None:
            self.ticket_status_label.setText("ابتدا یک تیکت و یک فاکتور انتخاب کنید.")
            return
        aftersales_service.link_ticket_invoice(self._selected_ticket_id, invoice_id)
        self.ticket_status_label.setText("")
        self.refresh()

    def _add_part_used(self) -> None:
        item_id = self.ticket_part_item_combo.currentData()
        if self._selected_ticket_id is None or item_id is None:
            self.ticket_status_label.setText("ابتدا یک تیکت و کالا را انتخاب کنید.")
            return
        try:
            quantity = decimal.Decimal(self.ticket_part_qty_field.text().strip() or "0")
        except decimal.InvalidOperation:
            self.ticket_status_label.setText("مقدار نامعتبر است.")
            return
        if quantity <= 0:
            self.ticket_status_label.setText("مقدار باید بزرگ‌تر از صفر باشد.")
            return
        aftersales_service.record_part_used(self._selected_ticket_id, item_id, quantity)
        self.ticket_part_qty_field.clear()
        self.ticket_status_label.setText("")
        self._refresh_ticket_parts()

    def _refresh_tickets(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        customers_by_id = {c["detail_account_id"]: c for c in self._customers}
        tickets = aftersales_service.list_tickets(company_id)
        self.ticket_table.setRowCount(len(tickets))
        for row_index, t in enumerate(tickets):
            customer = customers_by_id.get(t.customer_detail_account_id)
            values = [
                t.subject, f"{customer['code']} — {customer['name'] or ''}" if customer else str(t.customer_detail_account_id),
                _TICKET_STATUS_LABELS.get(t.status_code, t.status_code), "بله" if t.is_billable else "خیر",
            ]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, t.ticket_id)
                self.ticket_table.setItem(row_index, col_index, cell)

    # --- RMA -----------------------------------------------------------------
    def _build_rma_tab(self) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)

        left = QVBoxLayout()
        self.rma_table = QTableWidget(0, 4)
        self.rma_table.setHorizontalHeaderLabels(["مشتری", "دلیل", "مقدارِ درخواستی", "وضعیت"])
        self.rma_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rma_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rma_table.verticalHeader().setVisible(False)
        self.rma_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.rma_table.cellClicked.connect(self._on_rma_selected)
        left.addWidget(self.rma_table, stretch=1)

        self.rma_customer_combo = QComboBox()
        self.rma_customer_combo.currentIndexChanged.connect(self._on_rma_customer_selected)
        self.rma_document_combo = QComboBox()
        self.rma_reason_combo = QComboBox()
        for code, label in _RMA_REASON_LABELS.items():
            self.rma_reason_combo.addItem(label, code)
        self.rma_quantity_field = QLineEdit()
        self.rma_quantity_field.setPlaceholderText("مقدارِ درخواستی")
        self.rma_form_grid = FieldGrid([
            FieldSpec("customer", "مشتری", self.rma_customer_combo, span=2),
            FieldSpec("document", "فاکتورِ اصلی", self.rma_document_combo, span=2),
            FieldSpec("reason", "دلیل", self.rma_reason_combo, span=1),
            FieldSpec("quantity", "مقدارِ درخواستی", self.rma_quantity_field, span=1),
        ])
        self._rma_layout_controller = _TabLayoutController()
        self._rma_layout_controller.register_field_grids("commercial_aftersales_rma", [self.rma_form_grid])
        rma_form = QVBoxLayout()
        rma_form.addWidget(self.rma_form_grid)
        add_rma_button = QPushButton("🔁")
        add_rma_button.setObjectName("primaryIconButton")
        add_rma_button.setFixedWidth(48)
        add_rma_button.setToolTip("درخواستِ RMA")
        add_rma_button.clicked.connect(self._add_rma)
        rma_form.addWidget(add_rma_button)
        left.addLayout(rma_form)
        outer.addLayout(left, stretch=2)

        right = QVBoxLayout()
        right.addWidget(QLabel("تاییدِ RMAیِ انتخاب‌شده (سندِ برگشت‌ازفروش خودکار ساخته می‌شود)"))
        self.rma_warehouse_combo = QComboBox()
        right.addWidget(self.rma_warehouse_combo)
        approve_row = QHBoxLayout()
        approve_button = QPushButton("✅")
        approve_button.setObjectName("primaryIconButton")
        approve_button.setFixedWidth(48)
        approve_button.setToolTip("تاییدِ RMA")
        approve_button.clicked.connect(self._approve_rma)
        approve_row.addWidget(approve_button)
        reject_button = QPushButton("❌")
        reject_button.setObjectName("dangerIconButton")
        reject_button.setFixedWidth(44)
        reject_button.setToolTip("ردِ RMA")
        reject_button.clicked.connect(self._reject_rma)
        approve_row.addWidget(reject_button)
        right.addLayout(approve_row)

        self.rma_status_label = QLabel("")
        self.rma_status_label.setObjectName("statusError")
        right.addWidget(self.rma_status_label)
        right.addStretch(1)
        outer.addLayout(right, stretch=1)
        return wrap_scrollable(page)

    def _on_rma_customer_selected(self) -> None:
        self.rma_document_combo.clear()
        company_id = self._company_id()
        customer_id = self.rma_customer_combo.currentData()
        if company_id is None or customer_id is None:
            return
        documents = documents_service.list_documents(company_id, document_type_code="SALES_INVOICE", status_code="POSTED")
        for d in documents:
            if d.counterparty_detail_account_id == customer_id:
                self.rma_document_combo.addItem(f"فاکتورِ شمارهٔ {d.document_no}", d.document_id)

    def _add_rma(self) -> None:
        customer_id = self.rma_customer_combo.currentData()
        document_id = self.rma_document_combo.currentData()
        if customer_id is None or document_id is None:
            self.rma_status_label.setText("مشتری و فاکتورِ اصلی را انتخاب کنید.")
            return
        try:
            quantity = decimal.Decimal(self.rma_quantity_field.text().strip() or "0")
        except decimal.InvalidOperation:
            self.rma_status_label.setText("مقدار نامعتبر است.")
            return
        if quantity <= 0:
            self.rma_status_label.setText("مقدار باید بزرگ‌تر از صفر باشد.")
            return
        try:
            aftersales_service.request_rma(customer_id, document_id, self.rma_reason_combo.currentData(), quantity)
        except ValueError as exc:
            self.rma_status_label.setText(str(exc))
            return
        self.rma_quantity_field.clear()
        self.rma_status_label.setText("")
        self.refresh()

    def _on_rma_selected(self, row: int, _column: int) -> None:
        self._selected_rma_id = self.rma_table.item(row, 0).data(Qt.UserRole)

    def _approve_rma(self) -> None:
        company_id = self._company_id()
        warehouse_id = self.rma_warehouse_combo.currentData()
        if self._selected_rma_id is None:
            self.rma_status_label.setText("ابتدا یک RMA را از فهرست انتخاب کنید.")
            return
        if company_id is None or warehouse_id is None:
            self.rma_status_label.setText("انبار را انتخاب کنید.")
            return
        try:
            aftersales_service.approve_rma(
                self._selected_rma_id, company_id, app_session.current_user.user_id, warehouse_id,
                app_session.current_company.base_currency_id,
            )
        except ValueError as exc:
            self.rma_status_label.setText(str(exc))
            return
        self.rma_status_label.setText("")
        self.refresh()

    def _reject_rma(self) -> None:
        if self._selected_rma_id is None:
            self.rma_status_label.setText("ابتدا یک RMA را از فهرست انتخاب کنید.")
            return
        try:
            aftersales_service.reject_rma(self._selected_rma_id)
        except ValueError as exc:
            self.rma_status_label.setText(str(exc))
            return
        self.rma_status_label.setText("")
        self.refresh()

    def _refresh_rma(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        customers_by_id = {c["detail_account_id"]: c for c in self._customers}
        rma_requests = aftersales_service.list_rma_requests(company_id)
        self.rma_table.setRowCount(len(rma_requests))
        for row_index, r in enumerate(rma_requests):
            customer = customers_by_id.get(r.customer_detail_account_id)
            values = [
                f"{customer['code']} — {customer['name'] or ''}" if customer else str(r.customer_detail_account_id),
                _RMA_REASON_LABELS.get(r.reason_code, r.reason_code), str(r.requested_quantity),
                _RMA_STATUS_LABELS.get(r.status_code, r.status_code),
            ]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, r.rma_id)
                self.rma_table.setItem(row_index, col_index, cell)

    # --- بارگذاریِ کلی -------------------------------------------------------
    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._items = catalog_service.list_items(company_id, active_only=True)
        self._customers = dimensions_service.list_customers(company_id)

        self.warranty_invoice_combo.blockSignals(True)
        self.warranty_invoice_combo.clear()
        for d in documents_service.list_documents(company_id, document_type_code="SALES_INVOICE", status_code="POSTED"):
            self.warranty_invoice_combo.addItem(f"فاکتورِ شمارهٔ {d.document_no}", d.document_id)
        self.warranty_invoice_combo.blockSignals(False)
        self._on_warranty_invoice_selected()

        self.ticket_customer_combo.clear()
        self.rma_customer_combo.blockSignals(True)
        self.rma_customer_combo.clear()
        for c in self._customers:
            label = f"{c['code']} — {c['name'] or ''}"
            self.ticket_customer_combo.addItem(label, c["detail_account_id"])
            self.rma_customer_combo.addItem(label, c["detail_account_id"])
        self.rma_customer_combo.blockSignals(False)
        self._on_rma_customer_selected()

        self.ticket_item_combo.clear()
        self.ticket_item_combo.addItem("(بدونِ کالایِ مشخص)", None)
        self.ticket_part_item_combo.clear()
        for it in self._items:
            label = f"{it.code} — {it.name or ''}"
            self.ticket_item_combo.addItem(label, it.item_id)
            self.ticket_part_item_combo.addItem(label, it.item_id)

        self.ticket_warranty_combo.clear()
        self.ticket_warranty_combo.addItem("(بدونِ گارانتی)", None)
        for w in aftersales_service.list_warranties(company_id):
            self.ticket_warranty_combo.addItem(f"گارانتیِ #{w.warranty_id}", w.warranty_id)

        self.ticket_invoice_combo.clear()
        for d in documents_service.list_documents(company_id, document_type_code="SALES_INVOICE"):
            self.ticket_invoice_combo.addItem(f"فاکتورِ شمارهٔ {d.document_no}", d.document_id)

        self.rma_warehouse_combo.clear()
        for w in locations_service.list_warehouses(company_id, active_only=True):
            self.rma_warehouse_combo.addItem(f"{w.code} — {w.name}", w.warehouse_id)

        self._refresh_warranties()
        self._refresh_tickets()
        self._refresh_rma()
