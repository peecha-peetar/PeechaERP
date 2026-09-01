"""زیرماژولِ «مدیریتِ سفارشات» — طبقِ درخواستِ صریح: انتخابِ یک تفصیلیِ
خاص از گروهِ تفصیلیِ «سفارشاتِ در راه» در بالایِ فرم، ثبتِ پرداخت‌هایِ
مختلف (هر روش/ارزی) با بازکردنِ همان فرمِ دریافت/پرداختِ خزانه‌داری
(سندِ حسابداریِ هر پرداخت دقیقاً همان‌جا صادر می‌شود)، الصاقِ عکس برایِ
هر پرداخت، و درنهایت بستنِ سفارش."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
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
from peecha.services import companies as companies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import order_tracking as order_tracking_service
from peecha.services import treasury as treasury_service
from peecha.ui.widgets import FieldHelpMixin, FormScreenBase, add_quick_add_button


class OrderTrackingScreen(FieldHelpMixin, FormScreenBase):
    def __init__(self, main_window) -> None:
        super().__init__()
        self._main_window = main_window
        self._selected_order: order_tracking_service.OrderRow | None = None
        self._decimal_places = 0

        title = QLabel("مدیریتِ سفارشات")
        title.setObjectName("pageTitle")
        self.body_layout.addWidget(title)

        # طبقِ درخواستِ صریح («یک تفصیلیِ خاص از یک گروهِ تفصیلی بنامِ
        # سفارشاتِ در راه»): تنظیمِ یک‌بارهٔ همین گروه، بالایِ خودِ همین
        # صفحه (بدونِ نیازِ به یک صفحهٔ تنظیماتِ جداگانه).
        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("گروهِ تفصیلیِ «سفارشاتِ در راه»:"))
        self.dimension_combo = QComboBox()
        settings_row.addWidget(self.dimension_combo, stretch=1)
        save_dimension_button = QPushButton("ذخیره")
        save_dimension_button.setToolTip("تعیینِ گروهِ تفصیلی‌ای که هر «سفارش» یک عضوِ آن است")
        save_dimension_button.clicked.connect(self._save_dimension_setting)
        settings_row.addWidget(save_dimension_button)
        self.body_layout.addLayout(settings_row)

        # انتخابِ سفارش
        order_row = QHBoxLayout()
        order_row.addWidget(QLabel("سفارش:"))
        self.order_combo = QComboBox()
        self.order_combo.currentIndexChanged.connect(self._on_order_selected)
        order_row.addWidget(self.order_combo, stretch=1)
        self.order_status_label = QLabel("")
        order_row.addWidget(self.order_status_label)
        self.close_button = QPushButton("🔒 بستنِ سفارش")
        self.close_button.clicked.connect(self._close_order)
        order_row.addWidget(self.close_button)
        self.reopen_button = QPushButton("🔓 بازگشاییِ سفارش")
        self.reopen_button.clicked.connect(self._reopen_order)
        order_row.addWidget(self.reopen_button)
        self.body_layout.addLayout(order_row)

        # سفارشِ تازه: طبقِ گزارشِ صریح («یک گروهِ تفصیلی انتخاب می‌کنم،
        # تفصیلی‌هایِ سطحِ آخرش را باید نمایش بدهد») -- این کمبو دقیقاً
        # همان تفصیلی‌هایِ سطحِ آخرِ گروهِ تنظیم‌شده را نشان می‌دهد (که هنوز
        # به‌عنوانِ سفارش پیگیری نمی‌شوند)؛ دکمه‌یِ + هم‌الگو با بقیه‌یِ
        # برنامه، تفصیلیِ تازه را از صفحه‌یِ تعریفِ تفصیلی‌ها می‌سازد.
        new_order_row = QHBoxLayout()
        self.new_detail_combo = QComboBox()
        self.new_detail_combo.setEditable(True)
        self.new_detail_combo.setInsertPolicy(QComboBox.NoInsert)
        new_order_row.addWidget(self.new_detail_combo, stretch=1)
        add_quick_add_button(new_order_row, self.new_detail_combo, main_window, "GL_DIM", "تعریفِ تفصیلیِ تازه برایِ سفارش")
        self.new_description_field = QLineEdit()
        self.new_description_field.setPlaceholderText("شرحِ سفارش (اختیاری)")
        new_order_row.addWidget(self.new_description_field, stretch=1)
        add_order_button = QPushButton("➕ شروعِ پیگیریِ سفارش")
        add_order_button.clicked.connect(self._add_order)
        new_order_row.addWidget(add_order_button)
        self.body_layout.addLayout(new_order_row)

        self.balance_label = QLabel("")
        self.body_layout.addWidget(self.balance_label)

        payment_row = QHBoxLayout()
        self.add_payment_button = QPushButton("➕ افزودنِ پرداخت")
        self.add_payment_button.setToolTip(
            "فرمِ دریافت/پرداختِ خزانه‌داری با تفصیلیِ همین سفارش باز می‌شود — "
            "هر روش (نقد/بانک/چک/ارزی) که آن‌جا موجود است قابلِ‌استفاده است؛ "
            "سندِ حسابداری همان‌جا صادر می‌شود."
        )
        self.add_payment_button.clicked.connect(self._open_payment_form)
        payment_row.addWidget(self.add_payment_button)
        refresh_button = QPushButton("🔄 بروزرسانیِ فهرست")
        refresh_button.clicked.connect(self._refresh_payments)
        payment_row.addWidget(refresh_button)
        payment_row.addStretch(1)
        self.body_layout.addLayout(payment_row)

        self.payments_table = QTableWidget(0, 5)
        self.payments_table.setHorizontalHeaderLabels(["تاریخ", "شرح", "بدهکار", "بستانکار", "عکس"])
        self.payments_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.payments_table.verticalHeader().setVisible(False)
        self.payments_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.payments_table.setColumnWidth(0, 110)
        self.payments_table.setColumnWidth(2, 120)
        self.payments_table.setColumnWidth(3, 120)
        self.payments_table.setColumnWidth(4, 90)
        self.body_layout.addWidget(self.payments_table, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        self.body_layout.addWidget(self.status_label)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._decimal_places = companies_service.get_base_currency_decimal_places(company_id)

        self.dimension_combo.blockSignals(True)
        self.dimension_combo.clear()
        for row in dimensions_service.list_dimension_types(company_id):
            self.dimension_combo.addItem(row.code, row.dimension_type_id)
        current_dimension_type_id = order_tracking_service.get_dimension_type_id(company_id)
        if current_dimension_type_id is not None:
            idx = self.dimension_combo.findData(current_dimension_type_id)
            if idx >= 0:
                self.dimension_combo.setCurrentIndex(idx)
        self.dimension_combo.blockSignals(False)

        self.order_combo.blockSignals(True)
        self.order_combo.clear()
        for order in order_tracking_service.list_orders(company_id):
            status_label = "بسته" if order.status_code == "CLOSED" else "باز"
            self.order_combo.addItem(f"{order.code} — {order.name or ''} ({status_label})", order.order_tracking_id)
        self.order_combo.blockSignals(False)
        self._on_order_selected()

        self.new_detail_combo.blockSignals(True)
        self.new_detail_combo.clear()
        for detail_account in order_tracking_service.list_available_detail_accounts(company_id):
            label = f"{detail_account.full_code} — {detail_account.name}" if detail_account.name else detail_account.full_code
            self.new_detail_combo.addItem(label, detail_account.detail_account_id)
        self.new_detail_combo.setCurrentIndex(-1)
        self.new_detail_combo.blockSignals(False)

    def _save_dimension_setting(self) -> None:
        company_id = self._company_id()
        dimension_type_id = self.dimension_combo.currentData()
        if company_id is None or dimension_type_id is None:
            self.status_label.setText("ابتدا یک گروهِ تفصیلی انتخاب کنید.")
            return
        order_tracking_service.set_dimension_type_id(company_id, dimension_type_id)
        self.status_label.setText("")
        self.status_label.setObjectName("statusOk")
        self.status_label.setText("گروهِ تفصیلیِ «سفارشاتِ در راه» ذخیره شد.")
        # طبقِ گزارشِ صریح: بلافاصله بعدِ ذخیره، تفصیلی‌هایِ سطحِ آخرِ همین
        # گروه در کمبویِ «سفارشِ تازه» نمایش داده شوند -- بدونِ نیازِ کاربر
        # به خروج/ورودِ دوباره به این صفحه.
        self.refresh()

    def _add_order(self) -> None:
        company_id = self._company_id()
        user = app_session.current_user
        if company_id is None or user is None:
            return
        detail_account_id = self.new_detail_combo.currentData()
        if detail_account_id is None:
            self.status_label.setObjectName("statusError")
            self.status_label.setText("یک تفصیلی از گروهِ «سفارشاتِ در راه» انتخاب کنید.")
            return
        description = self.new_description_field.text().strip() or None
        try:
            order_tracking_service.create_order(company_id, user.user_id, detail_account_id, description)
        except ValueError as exc:
            self.status_label.setObjectName("statusError")
            self.status_label.setText(str(exc))
            return
        self.new_description_field.clear()
        self.status_label.setText("")
        self.refresh()

    def _on_order_selected(self) -> None:
        company_id = self._company_id()
        order_tracking_id = self.order_combo.currentData()
        if company_id is None or order_tracking_id is None:
            self._selected_order = None
            self.order_status_label.setText("")
            self.balance_label.setText("")
            self.payments_table.setRowCount(0)
            self.close_button.setEnabled(False)
            self.reopen_button.setEnabled(False)
            self.add_payment_button.setEnabled(False)
            return
        self._selected_order = order_tracking_service.get_order(order_tracking_id, company_id)
        if self._selected_order is None:
            return
        is_open = self._selected_order.status_code == "OPEN"
        self.order_status_label.setText("وضعیت: باز" if is_open else "وضعیت: بسته")
        self.close_button.setEnabled(is_open)
        self.reopen_button.setEnabled(not is_open)
        self.add_payment_button.setEnabled(is_open)
        self._refresh_balance()
        self._refresh_payments()

    def _refresh_balance(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_order is None:
            self.balance_label.setText("")
            return
        balance, nature = treasury_service.get_counterparty_balance(company_id, self._selected_order.detail_account_id)
        self.balance_label.setText(f"ماندهٔ فعلیِ سفارش: {numerals.format_money(balance, self._decimal_places)} ({nature})")

    def _refresh_payments(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_order is None:
            self.payments_table.setRowCount(0)
            return
        payments = order_tracking_service.list_order_payments(company_id, self._selected_order.detail_account_id)
        self.payments_table.setRowCount(len(payments))
        for row_index, payment in enumerate(payments):
            values = [
                numerals.to_persian_digits(payment.document_date.isoformat()), payment.description,
                numerals.format_money(payment.debit, self._decimal_places) if payment.debit else "",
                numerals.format_money(payment.credit, self._decimal_places) if payment.credit else "",
            ]
            for col_index, value in enumerate(values):
                self.payments_table.setItem(row_index, col_index, QTableWidgetItem(value))
            has_photo = bool(order_tracking_service.list_photos(company_id, payment.journal_entry_id))
            photo_button = QPushButton("📎" if has_photo else "➕📷")
            photo_button.setToolTip("افزودنِ عکس" if not has_photo else "این پرداخت عکس دارد — افزودنِ عکسِ دیگر")
            photo_button.clicked.connect(
                lambda _checked=False, journal_entry_id=payment.journal_entry_id: self._attach_photo(journal_entry_id)
            )
            self.payments_table.setCellWidget(row_index, 4, photo_button)

    def _open_payment_form(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_order is None:
            return
        dimension_type_id = order_tracking_service.get_dimension_type_id(company_id)
        mappings = treasury_service.list_counterparty_mappings(company_id, "PAYMENT")
        if not any(m.dimension_type_id == dimension_type_id for m in mappings):
            QMessageBox.warning(
                self, "تنظیمِ ناقص",
                "برایِ اینکه این سفارش در فرمِ پرداخت قابلِ‌انتخاب باشد، ابتدا باید در «تنظیماتِ خزانه‌داری → "
                "طرفِ‌حساب‌هایِ دریافت/پرداخت» یک حساب برایِ همین گروهِ تفصیلی (جهتِ پرداخت) مشخص کنید.",
            )
            return
        description = f"پرداختِ سفارشِ {self._selected_order.code} — {self._selected_order.name or ''}"
        detail_account_id = self._selected_order.detail_account_id
        self._main_window.open_screen(
            "TREASURY_PAYMENT",
            then=lambda screen: screen.prefill_for_invoice(detail_account_id, decimal.Decimal(0), description),
        )

    def _attach_photo(self, journal_entry_id: int) -> None:
        company_id = self._company_id()
        user = app_session.current_user
        if company_id is None or user is None:
            return
        file_path, _ = QFileDialog.getOpenFileName(self, "انتخابِ عکس", "", "تصاویر (*.png *.jpg *.jpeg *.webp)")
        if not file_path:
            return
        try:
            order_tracking_service.attach_photo(company_id, journal_entry_id, user.user_id, file_path)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh_payments()

    def _close_order(self) -> None:
        company_id = self._company_id()
        user = app_session.current_user
        if company_id is None or user is None or self._selected_order is None:
            return
        balance, nature = treasury_service.get_counterparty_balance(company_id, self._selected_order.detail_account_id)
        if balance != 0:
            confirm = QMessageBox.question(
                self, "بستنِ سفارش",
                f"مانده‌یِ این سفارش هنوز صفر نیست ({numerals.format_money(balance, self._decimal_places)} {nature}). "
                "همچنان بسته شود؟",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return
        try:
            order_tracking_service.close_order(self._selected_order.order_tracking_id, company_id, user.user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()

    def _reopen_order(self) -> None:
        company_id = self._company_id()
        if company_id is None or self._selected_order is None:
            return
        try:
            order_tracking_service.reopen_order(self._selected_order.order_tracking_id, company_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self.refresh()
