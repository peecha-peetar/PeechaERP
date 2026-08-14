"""فروشِ حضوری (POS، مرحلهٔ ۷) — سبدِ خرید روی یک SALES_INVOICEِ معمولی
با channel نداشته و pos_session_id، به‌علاوهٔ پرداختِ چندروشی."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session as app_session
from peecha.services import commercial_documents as documents_service
from peecha.services import commercial_pos as pos_service
from peecha.services import commercial_pricing as pricing_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import inventory_catalog as catalog_service
from peecha.ui.screens.journal_entry import _fill_options, _make_searchable_combo

_PAYMENT_METHOD_LABELS = {"CASH": "نقد", "CARD": "کارت‌خوان", "WALLET": "کیفِ‌پول", "GIFT_CARD": "کارتِ‌هدیه", "STORE_CREDIT": "اعتبارِ فروشگاهی"}


class CommercialPosSaleScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._items: list[catalog_service.ItemRow] = []
        self._document_id: int | None = None
        self._lines: list = []
        self._is_posted = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(12)

        title = QLabel("فروشِ حضوری (صندوق)")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("ترمینال"))
        self.terminal_combo = QComboBox()
        self.terminal_combo.currentIndexChanged.connect(self._on_terminal_changed)
        header_row.addWidget(self.terminal_combo)
        header_row.addWidget(QLabel("مشتری"))
        self.customer_combo = _make_searchable_combo([])
        header_row.addWidget(self.customer_combo)
        header_row.addWidget(QLabel("فهرستِ قیمت"))
        self.price_list_combo = QComboBox()
        header_row.addWidget(self.price_list_combo)
        outer.addLayout(header_row)

        self.session_label = QLabel("")
        outer.addWidget(self.session_label)

        new_sale_button = QPushButton("🆕")
        new_sale_button.setObjectName("iconButton")
        new_sale_button.setFixedWidth(34)
        new_sale_button.setToolTip("فروشِ تازه")
        new_sale_button.clicked.connect(self._reset_sale)
        outer.addWidget(new_sale_button, alignment=Qt.AlignLeft)

        line_form = QHBoxLayout()
        self.item_combo = _make_searchable_combo([])
        line_form.addWidget(self.item_combo, stretch=2)
        self.quantity_field = QDoubleSpinBox()
        self.quantity_field.setDecimals(2)
        self.quantity_field.setRange(0.01, 999999)
        self.quantity_field.setValue(1)
        line_form.addWidget(self.quantity_field)
        self.unit_price_field = QDoubleSpinBox()
        self.unit_price_field.setDecimals(2)
        self.unit_price_field.setRange(0, 999999999999)
        self.unit_price_field.setSpecialValueText(" ")
        self.unit_price_field.setToolTip("خالی = محاسبهٔ خودکار از فهرستِ قیمت")
        line_form.addWidget(self.unit_price_field)
        add_line_button = QPushButton("➕")
        add_line_button.setObjectName("primaryIconButton")
        add_line_button.setFixedWidth(40)
        add_line_button.setToolTip("افزودنِ کالا")
        add_line_button.clicked.connect(self._add_line)
        line_form.addWidget(add_line_button)
        outer.addLayout(line_form)

        self.lines_table = QTableWidget(0, 4)
        self.lines_table.setHorizontalHeaderLabels(["کالا", "مقدار", "بهایِ واحد", "جمعِ ردیف"])
        self.lines_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lines_table.verticalHeader().setVisible(False)
        self.lines_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        outer.addWidget(self.lines_table)

        self.total_label = QLabel("جمعِ کل: ۰")
        self.total_label.setObjectName("sectionTitle")
        outer.addWidget(self.total_label)

        finalize_button = QPushButton("✅")
        finalize_button.setObjectName("primaryIconButton")
        finalize_button.setFixedWidth(40)
        finalize_button.setToolTip("تکمیلِ فروش (تاییدِ نهایی)")
        finalize_button.clicked.connect(self._finalize_sale)
        outer.addWidget(finalize_button, alignment=Qt.AlignLeft)

        payments_title = QLabel("پرداخت")
        payments_title.setObjectName("sectionTitle")
        outer.addWidget(payments_title)

        payment_form = QHBoxLayout()
        self.payment_method_combo = QComboBox()
        for code, label in _PAYMENT_METHOD_LABELS.items():
            self.payment_method_combo.addItem(label, code)
        payment_form.addWidget(self.payment_method_combo)
        self.payment_amount_field = QDoubleSpinBox()
        self.payment_amount_field.setDecimals(2)
        self.payment_amount_field.setRange(0, 999999999)
        payment_form.addWidget(self.payment_amount_field)
        self.payment_reference_field = QLineEdit()
        self.payment_reference_field.setPlaceholderText("کدِ کارتِ‌هدیه / شمارهٔ مرجع")
        payment_form.addWidget(self.payment_reference_field)
        add_payment_button = QPushButton("💰")
        add_payment_button.setObjectName("iconButton")
        add_payment_button.setFixedWidth(34)
        add_payment_button.setToolTip("افزودنِ پرداخت")
        add_payment_button.clicked.connect(self._add_payment)
        payment_form.addWidget(add_payment_button)
        outer.addLayout(payment_form)

        self.payments_label = QLabel("")
        outer.addWidget(self.payments_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)
        outer.addStretch(1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._items = catalog_service.list_items(company_id, active_only=True)
        _fill_options(self.item_combo, [(it.item_id, f"{it.code} — {it.name or ''}") for it in self._items])

        current_terminal = self.terminal_combo.currentData()
        self.terminal_combo.blockSignals(True)
        self.terminal_combo.clear()
        for t in pos_service.list_terminals(company_id):
            self.terminal_combo.addItem(f"{t.code} — {t.name}", t.terminal_id)
        if current_terminal is not None:
            index = self.terminal_combo.findData(current_terminal)
            if index >= 0:
                self.terminal_combo.setCurrentIndex(index)
        self.terminal_combo.blockSignals(False)

        settings = pos_service.get_pos_settings(company_id)
        customer_options = [(c["detail_account_id"], f"{c['code']} — {c['name'] or ''}") for c in dimensions_service.list_customers(company_id)]
        _fill_options(self.customer_combo, customer_options)
        if settings is not None and settings.default_guest_customer_detail_account_id is not None:
            index = self.customer_combo.findData(settings.default_guest_customer_detail_account_id)
            if index >= 0:
                self.customer_combo.setCurrentIndex(index)

        self.price_list_combo.clear()
        self.price_list_combo.addItem("(بدونِ فهرستِ قیمت)", None)
        for pl in pricing_service.list_price_lists(company_id, "SALES"):
            self.price_list_combo.addItem(f"{pl.code} — {pl.name}", pl.price_list_id)

        self._update_session_label()

    def _current_open_session_id(self) -> int | None:
        terminal_id = self.terminal_combo.currentData()
        if terminal_id is None:
            return None
        session = pos_service.get_open_session(terminal_id)
        return session.session_id if session is not None else None

    def _on_terminal_changed(self) -> None:
        self._update_session_label()

    def _update_session_label(self) -> None:
        session_id = self._current_open_session_id()
        if session_id is None:
            self.session_label.setText("این ترمینال جلسهٔ بازی ندارد — ابتدا از صفحهٔ «ترمینال‌ها و جلسه‌هایِ صندوق» یک جلسه باز کنید.")
            self.session_label.setObjectName("statusError")
        else:
            self.session_label.setText(f"جلسهٔ باز — شناسه: {numerals.to_persian_digits(str(session_id))}")
            self.session_label.setObjectName("")
        self.session_label.style().unpolish(self.session_label)
        self.session_label.style().polish(self.session_label)

    def _reset_sale(self) -> None:
        self._document_id = None
        self._lines = []
        self._is_posted = False
        self.status_label.setText("")
        self.payments_label.setText("")
        self._refresh_lines_table()
        self.refresh()

    def _ensure_document(self) -> bool:
        if self._document_id is not None:
            return True
        company_id = self._company_id()
        session_id = self._current_open_session_id()
        customer_id = self.customer_combo.currentData()
        if company_id is None or session_id is None or customer_id is None:
            self.status_label.setText("ترمینال با جلسهٔ باز و مشتری را انتخاب کنید.")
            return False
        terminal_id = self.terminal_combo.currentData()
        from peecha.services import commercial_pos as _pos

        terminal = next((t for t in _pos.list_terminals(company_id) if t.terminal_id == terminal_id), None)
        try:
            self._document_id = documents_service.create_document(
                company_id, app_session.current_user.user_id, "SALES_INVOICE", datetime.date.today(),
                documents_service.DocumentHeaderFields(
                    counterparty_detail_account_id=customer_id, currency_id=app_session.current_company.base_currency_id,
                    warehouse_id=terminal.warehouse_id if terminal else None,
                    price_list_id=self.price_list_combo.currentData(), pos_session_id=session_id,
                ),
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return False
        return True

    def _add_line(self) -> None:
        if self._is_posted:
            self.status_label.setText("این فروش قبلاً نهایی شده — برایِ فروشِ تازه، «فروشِ تازه» را بزنید.")
            return
        if not self._ensure_document():
            return
        item_id = self.item_combo.currentData()
        item = next((it for it in self._items if it.item_id == item_id), None)
        if item is None:
            self.status_label.setText("کالا را انتخاب کنید.")
            return
        quantity = decimal.Decimal(str(self.quantity_field.value()))
        unit_price = decimal.Decimal(str(self.unit_price_field.value())) if self.unit_price_field.value() > 0 else None
        try:
            documents_service.add_line(
                self._document_id, self._company_id(), item.item_id, item.base_uom_id, quantity, quantity, unit_price=unit_price,
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("")
        self.unit_price_field.setValue(0)
        self.quantity_field.setValue(1)
        self._load_document()

    def _load_document(self) -> None:
        if self._document_id is None:
            return
        doc, lines = documents_service.get_document(self._document_id, self._company_id())
        self._lines = lines
        self._is_posted = doc.status_code == "POSTED"
        self._refresh_lines_table()
        self.total_label.setText(f"جمعِ کل: {numerals.format_amount(doc.total_amount)}")
        self._refresh_payments_label(doc.total_amount)

    def _refresh_lines_table(self) -> None:
        items_by_id = {it.item_id: it for it in self._items}
        self.lines_table.setRowCount(len(self._lines))
        for row_index, ln in enumerate(self._lines):
            item = items_by_id.get(ln.item_id)
            values = [
                f"{item.code} — {item.name or ''}" if item else str(ln.item_id),
                str(ln.quantity), str(ln.unit_price), str(ln.line_total),
            ]
            for col_index, value in enumerate(values):
                self.lines_table.setItem(row_index, col_index, QTableWidgetItem(value))

    def _finalize_sale(self) -> None:
        if self._document_id is None or not self._lines:
            self.status_label.setText("ابتدا حداقل یک کالا به سبد اضافه کنید.")
            return
        if self._is_posted:
            self.status_label.setText("این فروش قبلاً نهایی شده است.")
            return
        company_id = self._company_id()
        try:
            documents_service.confirm_document(self._document_id, company_id, app_session.current_user.user_id)
            documents_service.post_document(self._document_id, company_id, app_session.current_user.user_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("")
        self._load_document()

    def _add_payment(self) -> None:
        if self._document_id is None:
            self.status_label.setText("ابتدا حداقل یک کالا به سبد اضافه کنید.")
            return
        method_code = self.payment_method_combo.currentData()
        amount = decimal.Decimal(str(self.payment_amount_field.value()))
        if amount <= 0:
            self.status_label.setText("مبلغِ پرداخت باید بزرگ‌تر از صفر باشد.")
            return
        reference = self.payment_reference_field.text().strip() or None
        try:
            if method_code == "GIFT_CARD":
                if not reference:
                    self.status_label.setText("کدِ کارتِ‌هدیه را وارد کنید.")
                    return
                pos_service.redeem_gift_card(reference, amount)
            pos_service.record_payment(self._document_id, method_code, amount, reference_no=reference)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.payment_amount_field.setValue(0)
        self.payment_reference_field.clear()
        self.status_label.setText("")
        self._load_document()

    def _refresh_payments_label(self, total_amount: decimal.Decimal) -> None:
        covered = pos_service.payments_cover_total(self._document_id) if self._document_id else False
        self.payments_label.setText("پرداخت کامل شد." if covered else "پرداخت هنوز کامل نیست.")
