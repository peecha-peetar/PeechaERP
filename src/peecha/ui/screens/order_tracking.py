"""زیرماژولِ «مدیریتِ سفارشات» — طبقِ درخواستِ صریح: انتخابِ یک تفصیلیِ
خاص از گروهِ تفصیلیِ «سفارشاتِ در راه» در بالایِ فرم، ثبتِ پرداخت‌هایِ
مختلف (هر روش/ارزی) با بازکردنِ همان فرمِ دریافت/پرداختِ خزانه‌داری
(سندِ حسابداریِ هر پرداخت دقیقاً همان‌جا صادر می‌شود)، الصاقِ عکس برایِ
هر پرداخت، و درنهایت بستنِ سفارش."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session as app_session
from peecha.services import companies as companies_service
from peecha.services import currencies as currencies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import order_tracking as order_tracking_service
from peecha.services import treasury as treasury_service
from peecha.ui.screens.journal_entry import _AmountField
from peecha.ui.widgets import FieldHelpMixin, FormScreenBase, add_quick_add_button


class _PaymentCurrencyDialog(QDialog):
    """طبقِ درخواستِ صریح («اکثرا با ارزهای دیگه هم کار می‌کنن، بعدِ زدنِ
    کلیدِ پرداخت بپرسه ارز کدومه و چقدر بوده و نرخِ روز را وارد کنیم»):
    قبل از بازشدنِ فرمِ دریافت/پرداختِ خزانه‌داری، ارز/مبلغ/نرخِ همان
    پرداخت این‌جا پرسیده می‌شود -- فرمِ خزانه‌داری با همین سه مقدار
    پیش‌پر باز می‌شود (کاربر فقط روشِ پرداخت را انتخاب می‌کند)."""

    def __init__(
        self, company_id: int, base_currency_id: int, detail_account_id: int, decimal_places: int, parent=None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("مشخصاتِ پرداخت")
        self._company_id = company_id
        self._base_currency_id = base_currency_id
        self._detail_account_id = detail_account_id
        self._decimal_places = decimal_places
        self.result_currency_id: int | None = None
        self.result_amount: decimal.Decimal | None = None
        self.result_exchange_rate: decimal.Decimal | None = None
        self.result_title_label: str | None = None

        layout = QVBoxLayout(self)

        # طبقِ درخواستِ صریح: «عنوانِ پرداخت» (هزینه‌یِ ترخیص/بهایِ اولیه‌یِ
        # کالا/...) از یک فهرستِ قابلِ‌گسترش انتخاب می‌شود؛ دکمه‌یِ + همان‌جا
        # (بدونِ بستنِ همین دیالوگ) عنوانِ تازه اضافه می‌کند.
        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("عنوانِ پرداخت:"))
        self.title_combo = QComboBox()
        self._reload_titles()
        title_row.addWidget(self.title_combo, stretch=1)
        add_title_button = QPushButton("+")
        add_title_button.setObjectName("iconButton")
        add_title_button.setFixedWidth(28)
        add_title_button.setToolTip("افزودنِ عنوانِ پرداختِ تازه")
        add_title_button.clicked.connect(self._add_title)
        title_row.addWidget(add_title_button)
        # طبقِ گزارشِ صریح («عنوانِ پرداخت وقتی وارد می‌شود نمی‌شود حذف یا
        # ویرایش کرد»): دو دکمه‌یِ ویرایش/حذف، رویِ همان عنوانِ انتخاب‌شده
        # در کمبو -- ویرایش/حذفِ یک عنوان هیچ سندِ حسابداریِ قبلی را که
        # قبلاً با همان عنوان ثبت شده تغییر نمی‌دهد (شرحِ آن پرداخت‌ها یک
        # متنِ ثابتِ کپی‌شده است، نه ارجاعِ زنده).
        edit_title_button = QPushButton("✎")
        edit_title_button.setObjectName("iconButton")
        edit_title_button.setFixedWidth(28)
        edit_title_button.setToolTip("ویرایشِ عنوانِ انتخاب‌شده")
        edit_title_button.clicked.connect(self._edit_title)
        title_row.addWidget(edit_title_button)
        delete_title_button = QPushButton("🗑")
        delete_title_button.setObjectName("dangerIconButton")
        delete_title_button.setFixedWidth(28)
        delete_title_button.setToolTip("حذفِ عنوانِ انتخاب‌شده")
        delete_title_button.clicked.connect(self._delete_title)
        title_row.addWidget(delete_title_button)
        layout.addLayout(title_row)

        currency_row = QHBoxLayout()
        currency_row.addWidget(QLabel("ارز:"))
        self.currency_combo = QComboBox()
        for c in currencies_service.list_transactable_currencies(company_id):
            label = f"{c.iso_code} ({c.symbol})" if c.symbol else c.iso_code
            self.currency_combo.addItem(label, c.currency_id)
        currency_row.addWidget(self.currency_combo, stretch=1)
        layout.addLayout(currency_row)

        amount_row = QHBoxLayout()
        amount_row.addWidget(QLabel("مبلغ:"))
        self.amount_field = _AmountField()
        amount_row.addWidget(self.amount_field, stretch=1)
        layout.addLayout(amount_row)

        self.rate_row_widget = QWidget()
        rate_row = QHBoxLayout(self.rate_row_widget)
        rate_row.setContentsMargins(0, 0, 0, 0)
        rate_row.addWidget(QLabel("نرخِ روز:"))
        self.rate_field = QLineEdit()
        rate_row.addWidget(self.rate_field, stretch=1)
        layout.addWidget(self.rate_row_widget)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        layout.addWidget(self.status_label)

        # طبقِ درخواستِ صریح: «در فوترِ همین فرم جمعِ مانده را هم نمایش
        # بدهد» -- ماندهٔ فعلیِ همین سفارش، برایِ تصمیم‌گیریِ بهترِ کاربر
        # درباره‌یِ مبلغِ همین پرداخت.
        self.balance_footer_label = QLabel("")
        layout.addWidget(self.balance_footer_label)
        self._refresh_balance_footer()

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        ok_button = QPushButton("تایید و رفتن به فرمِ پرداخت")
        ok_button.clicked.connect(self._on_accept)
        button_row.addWidget(ok_button)
        cancel_button = QPushButton("انصراف")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

        self.currency_combo.currentIndexChanged.connect(self._on_currency_changed)
        self._on_currency_changed()

    def _on_currency_changed(self) -> None:
        currency_id = self.currency_combo.currentData()
        is_base = currency_id == self._base_currency_id
        self.rate_row_widget.setVisible(not is_base)
        if not is_base and currency_id is not None:
            latest = currencies_service.get_latest_rate(self._company_id, currency_id, datetime.date.today())
            self.rate_field.setText(numerals.format_amount(latest) if latest is not None else "")

    def _reload_titles(self, select_title_id: int | None = None) -> None:
        self.title_combo.clear()
        self.title_combo.addItem("— بدونِ عنوان —", None)
        for t in order_tracking_service.list_payment_titles(self._company_id):
            self.title_combo.addItem(t.label, t.payment_title_id)
        if select_title_id is not None:
            index = self.title_combo.findData(select_title_id)
            if index >= 0:
                self.title_combo.setCurrentIndex(index)

    def _add_title(self) -> None:
        label, ok = QInputDialog.getText(self, "افزودنِ عنوانِ پرداخت", "عنوانِ تازه (مثلاً «هزینه‌یِ ترخیص»):")
        if not ok or not label.strip():
            return
        try:
            title_id = order_tracking_service.create_payment_title(self._company_id, label)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._reload_titles(select_title_id=title_id)

    def _edit_title(self) -> None:
        title_id = self.title_combo.currentData()
        if title_id is None:
            QMessageBox.information(self, "ویرایشِ عنوان", "ابتدا یک عنوان از فهرست انتخاب کنید.")
            return
        new_label, ok = QInputDialog.getText(self, "ویرایشِ عنوانِ پرداخت", "عنوانِ تازه:", text=self.title_combo.currentText())
        if not ok or not new_label.strip():
            return
        try:
            order_tracking_service.update_payment_title(self._company_id, title_id, new_label)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._reload_titles(select_title_id=title_id)

    def _delete_title(self) -> None:
        title_id = self.title_combo.currentData()
        if title_id is None:
            QMessageBox.information(self, "حذفِ عنوان", "ابتدا یک عنوان از فهرست انتخاب کنید.")
            return
        confirm = QMessageBox.question(
            self, "حذفِ عنوان",
            f"عنوانِ «{self.title_combo.currentText()}» حذف شود؟ (سندهایِ پرداختِ قبلی که با این عنوان ثبت شده‌اند "
            "بدونِ تغییر باقی می‌مانند.)",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            order_tracking_service.delete_payment_title(self._company_id, title_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._reload_titles()

    def _refresh_balance_footer(self) -> None:
        balance, nature = treasury_service.get_counterparty_balance(self._company_id, self._detail_account_id)
        self.balance_footer_label.setText(
            f"ماندهٔ فعلیِ سفارش: {numerals.format_money(balance, self._decimal_places)} ({nature})"
        )

    def _on_accept(self) -> None:
        currency_id = self.currency_combo.currentData()
        amount = decimal.Decimal(str(self.amount_field.value()))
        if amount <= 0:
            self.status_label.setText("مبلغ را وارد کنید.")
            return
        exchange_rate = decimal.Decimal(1)
        if currency_id != self._base_currency_id:
            try:
                exchange_rate = numerals.parse_decimal(self.rate_field.text())
            except ValueError:
                exchange_rate = decimal.Decimal(0)
            if exchange_rate <= 0:
                self.status_label.setText("نرخِ روزِ ارز را وارد کنید.")
                return
        self.result_currency_id = currency_id
        self.result_amount = amount
        self.result_exchange_rate = exchange_rate
        self.result_title_label = self.title_combo.currentText() if self.title_combo.currentData() is not None else None
        self.accept()


class _PhotoManagerDialog(QDialog):
    """طبقِ گزارشِ صریح («ستونِ الصاقِ عکس هیچ آیکنی نداره، عکسِ الصاق‌شده
    پیش‌نمایش/حذف/تعویض ندارد»): با کلیک رویِ دکمهٔ عکسِ هر ردیف، این
    دیالوگ همه‌یِ عکس‌هایِ همان پرداخت را با یک پیش‌نمایشِ کوچک نشان
    می‌دهد -- هرکدام با دکمه‌یِ حذفِ خودش، به‌علاوه‌یِ دکمه‌یِ افزودنِ
    عکسِ تازه."""

    def __init__(self, company_id: int, journal_entry_id: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("عکس‌هایِ این پرداخت")
        self.resize(420, 420)
        self._company_id = company_id
        self._journal_entry_id = journal_entry_id

        layout = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.addStretch(1)
        scroll.setWidget(self._list_widget)
        layout.addWidget(scroll, stretch=1)

        add_button = QPushButton("➕ افزودنِ عکسِ تازه")
        add_button.clicked.connect(self._add_photo)
        layout.addWidget(add_button)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("بستن")
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)

        self._refresh()

    def _refresh(self) -> None:
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        photos = order_tracking_service.list_photos(self._company_id, self._journal_entry_id)
        for photo in photos:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            thumb_label = QLabel()
            thumb_label.setFixedSize(96, 96)
            pixmap = QPixmap(photo.storage_key)
            if not pixmap.isNull():
                thumb_label.setPixmap(pixmap.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                thumb_label.setText("—")
            row_layout.addWidget(thumb_label)
            name_label = QLabel(photo.file_name)
            row_layout.addWidget(name_label, stretch=1)
            delete_button = QPushButton("🗑")
            delete_button.setObjectName("dangerIconButton")
            delete_button.setFixedWidth(36)
            delete_button.setToolTip("حذفِ این عکس")
            delete_button.clicked.connect(
                lambda _checked=False, attachment_id=photo.attachment_id: self._delete_photo(attachment_id)
            )
            row_layout.addWidget(delete_button)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)
        if not photos:
            empty_label = QLabel("هنوز عکسی برایِ این پرداخت الصاق نشده.")
            self._list_layout.insertWidget(0, empty_label)

    def _add_photo(self) -> None:
        user = app_session.current_user
        if user is None:
            return
        file_path, _ = QFileDialog.getOpenFileName(self, "انتخابِ عکس", "", "تصاویر (*.png *.jpg *.jpeg *.webp)")
        if not file_path:
            return
        try:
            order_tracking_service.attach_photo(self._company_id, self._journal_entry_id, user.user_id, file_path)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh()

    def _delete_photo(self, attachment_id: int) -> None:
        user = app_session.current_user
        if user is None:
            return
        confirm = QMessageBox.question(self, "حذفِ عکس", "این عکس حذف شود؟", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            order_tracking_service.delete_photo(attachment_id, self._company_id, user.user_id)
        except ValueError as exc:
            QMessageBox.warning(self, "خطا", str(exc))
            return
        self._refresh()


class OrderTrackingScreen(FieldHelpMixin, FormScreenBase):
    def __init__(self, main_window) -> None:
        super().__init__()
        self._main_window = main_window
        self._selected_order: order_tracking_service.OrderRow | None = None
        self._decimal_places = 0
        self._base_currency_id: int | None = None
        self._currency_iso_by_id: dict[int, str] = {}

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

        # طبقِ درخواستِ صریح («ستون‌هایِ نوعِ ارز/نرخِ ارز/جمعِ مبلغِ
        # ارزی هم اضافه شود»): سه ستونِ آخر مبلغِ همان پرداخت را به ارزِ
        # خودش (نه لزوماً ارزِ پایه) نشان می‌دهند -- برایِ پرداختِ ریالی
        # خالی می‌مانند.
        self.payments_table = QTableWidget(0, 8)
        self.payments_table.setHorizontalHeaderLabels(
            ["تاریخ", "شرح", "بدهکار", "بستانکار", "ارز", "نرخِ ارز", "مبلغِ ارزی", "عکس"]
        )
        self.payments_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.payments_table.verticalHeader().setVisible(False)
        self.payments_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.payments_table.setColumnWidth(0, 110)
        self.payments_table.setColumnWidth(2, 120)
        self.payments_table.setColumnWidth(3, 120)
        self.payments_table.setColumnWidth(4, 70)
        self.payments_table.setColumnWidth(5, 100)
        self.payments_table.setColumnWidth(6, 120)
        self.payments_table.setColumnWidth(7, 90)
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
        self._base_currency_id = app_session.current_company.base_currency_id if app_session.current_company else None
        self._currency_iso_by_id = {c.currency_id: c.iso_code for c in currencies_service.list_all_currencies()}

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
            fc_amount = payment.debit_fc if payment.debit_fc else payment.credit_fc
            values = [
                numerals.to_persian_digits(payment.document_date.isoformat()), payment.description,
                numerals.format_money(payment.debit, self._decimal_places) if payment.debit else "",
                numerals.format_money(payment.credit, self._decimal_places) if payment.credit else "",
                "" if payment.is_base_currency else self._currency_iso_by_id.get(payment.currency_id, ""),
                "" if payment.is_base_currency else numerals.format_amount(payment.exchange_rate),
                "" if payment.is_base_currency else numerals.format_money(fc_amount, 2),
            ]
            for col_index, value in enumerate(values):
                self.payments_table.setItem(row_index, col_index, QTableWidgetItem(value))
            # طبقِ باگِ کشف‌شده: اگر فرمِ «مدیریتِ سفارشات» هنوز در
            # sec.forms ثبت نشده باشد، list_photos خطا می‌دهد -- این خطا
            # دیگر نباید کلِ جدول را (از همان ردیفِ اول به بعد) خالی
            # بگذارد، پس این‌جا مجزا محافظت می‌شود.
            try:
                has_photo = bool(order_tracking_service.list_photos(company_id, payment.journal_entry_id))
            except ValueError:
                has_photo = False
            # طبقِ گزارشِ صریح («ستونِ عکس هیچ آیکنی نداره»): بدونِ
            # objectName صریح، این دکمه از استایلِ عمومیِ QPushButton
            # (پدینگِ ۹px۱۸px) استفاده می‌کرد که در ستونِ باریکِ جدول
            # عملاً چیزی برایِ گلیف نمی‌گذاشت -- همان استایلِ استانداردِ
            # iconButton این‌جا هم اعمال شد.
            photo_button = QPushButton("📎" if has_photo else "➕📷")
            photo_button.setObjectName("iconButton")
            photo_button.setToolTip("مدیریتِ عکس‌هایِ این پرداخت (افزودن/پیش‌نمایش/حذف)")
            photo_button.clicked.connect(
                lambda _checked=False, journal_entry_id=payment.journal_entry_id: self._open_photo_manager(journal_entry_id)
            )
            self.payments_table.setCellWidget(row_index, 7, photo_button)

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
        # طبقِ درخواستِ صریح («اکثرا با ارزهای دیگه هم کار می‌کنن»): پیش
        # از بازکردنِ فرمِ خزانه‌داری، ارز/مبلغ/نرخ (و طبقِ گزارشِ بعدی،
        # عنوانِ پرداخت) همین‌جا پرسیده می‌شود.
        detail_account_id = self._selected_order.detail_account_id
        dialog = _PaymentCurrencyDialog(company_id, self._base_currency_id, detail_account_id, self._decimal_places, self)
        if dialog.exec() != QDialog.Accepted:
            return
        title_part = f"{dialog.result_title_label} — " if dialog.result_title_label else ""
        description = f"{title_part}پرداختِ سفارشِ {self._selected_order.code} — {self._selected_order.name or ''}"
        currency_id = dialog.result_currency_id
        amount = dialog.result_amount
        exchange_rate = dialog.result_exchange_rate
        self._main_window.open_screen(
            "TREASURY_PAYMENT",
            then=lambda screen: screen.prefill_for_invoice(
                detail_account_id, amount, description, currency_id=currency_id, exchange_rate=exchange_rate
            ),
        )

    def _open_photo_manager(self, journal_entry_id: int) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        dialog = _PhotoManagerDialog(company_id, journal_entry_id, self)
        dialog.exec()
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
