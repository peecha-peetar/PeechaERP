"""کوپن/کدِ تخفیفِ فروشگاهی -- طبقِ بازخوردِ صریحِ کاربر («امکاناتِ
حیاتیِ PeechaSync -- کوپن/کدِ تخفیفِ فروشگاهی»): کوپن در ERP تعریف
می‌شود و با دکمه‌یِ سینک به فروشگاهِ ووکامرس پوش می‌شود (V1، طبقِ
محدودیتِ همین دور فقط ووکامرس -- پرستاشاپ endpointِ ساده‌ای برایِ
کوپن ندارد)."""

from __future__ import annotations

import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session as app_session
from peecha.services import commercial_ecommerce as ecommerce_service
from peecha.ui import theme
from peecha.ui.widgets import JalaliDateEdit, LayoutEditMixin

_DISCOUNT_TYPE_LABELS = {"PERCENT": "درصدی", "FIXED_CART": "مبلغِ ثابت (کل سبد)", "FIXED_PRODUCT": "مبلغِ ثابت (هر کالا)"}
_SYNC_STATUS_LABELS = {"PENDING": "سینک‌نشده", "SYNCED": "سینک‌شده", "FAILED": "ناموفق"}


class CommercialCouponsScreen(LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._connections: list = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("کوپن/کدِ تخفیفِ فروشگاهی")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["اتصال", "کد", "نوعِ تخفیف", "مقدار", "معتبر تا", "وضعیتِ سینک"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        outer.addWidget(self.table, stretch=1)

        row_buttons = QHBoxLayout()
        sync_button = QPushButton("🔄 سینکِ کوپنِ انتخاب‌شده به فروشگاه")
        sync_button.clicked.connect(self._sync_selected)
        row_buttons.addWidget(sync_button)
        delete_button = QPushButton("🗑 حذفِ کوپنِ انتخاب‌شده")
        delete_button.clicked.connect(self._delete_selected)
        row_buttons.addWidget(delete_button)
        row_buttons.addStretch(1)
        outer.addLayout(row_buttons)

        form = QHBoxLayout()
        self.connection_combo = QComboBox()
        form.addWidget(self.connection_combo)
        self.code_field = QLineEdit()
        self.code_field.setPlaceholderText("کدِ کوپن (مثلاً SUMMER20)")
        form.addWidget(self.code_field, stretch=1)
        self.discount_type_combo = QComboBox()
        for code, label in _DISCOUNT_TYPE_LABELS.items():
            self.discount_type_combo.addItem(label, code)
        form.addWidget(self.discount_type_combo)
        self.amount_field = QLineEdit()
        self.amount_field.setPlaceholderText("مقدار")
        form.addWidget(self.amount_field)
        self.valid_until_field = JalaliDateEdit()
        form.addWidget(self.valid_until_field)
        self.no_expiry_checkbox = QCheckBox("بدونِ تاریخِ انقضا")
        self.no_expiry_checkbox.setChecked(True)
        self.no_expiry_checkbox.toggled.connect(self.valid_until_field.setDisabled)
        self.valid_until_field.setDisabled(True)
        form.addWidget(self.no_expiry_checkbox)
        add_button = QPushButton("➕")
        add_button.setObjectName("primaryIconButton")
        add_button.setFixedWidth(44)
        add_button.setToolTip("افزودنِ کوپن")
        add_button.clicked.connect(self._add_coupon)
        form.addWidget(add_button)
        outer.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        outer.addWidget(self.status_label)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def _selected_coupon_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item is not None else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._connections = [
            c for c in ecommerce_service.list_connections(company_id)
            if c.platform_code == "WOOCOMMERCE" and c.sync_status == "ACTIVE"
        ]
        self.connection_combo.clear()
        for c in self._connections:
            self.connection_combo.addItem(c.store_url, c.connection_id)
        connections_by_id = {c.connection_id: c for c in self._connections}

        coupons = ecommerce_service.list_coupons(company_id)
        self.table.setRowCount(len(coupons))
        for row_index, coupon in enumerate(coupons):
            connection = connections_by_id.get(coupon.connection_id)
            values = [
                connection.store_url if connection else str(coupon.connection_id),
                coupon.code,
                _DISCOUNT_TYPE_LABELS.get(coupon.discount_type_code, coupon.discount_type_code),
                numerals.format_money(coupon.amount, 2),
                coupon.valid_until.isoformat() if coupon.valid_until else "—",
                _SYNC_STATUS_LABELS.get(coupon.sync_status, coupon.sync_status),
            ]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col_index == 0:
                    cell.setData(Qt.UserRole, coupon.coupon_id)
                self.table.setItem(row_index, col_index, cell)

    def _add_coupon(self) -> None:
        company_id = self._company_id()
        connection_id = self.connection_combo.currentData()
        if company_id is None or connection_id is None:
            self.status_label.setText("ابتدا یک اتصالِ فعالِ ووکامرس لازم است.")
            return
        try:
            amount = decimal.Decimal(self.amount_field.text() or "0")
        except decimal.InvalidOperation:
            self.status_label.setText("مقدار نامعتبر است.")
            return
        valid_until = None if self.no_expiry_checkbox.isChecked() else self.valid_until_field.date()
        try:
            ecommerce_service.create_coupon(
                company_id, connection_id, self.code_field.text().strip(), self.discount_type_combo.currentData(),
                amount, valid_until=valid_until,
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.code_field.clear()
        self.amount_field.clear()
        self.status_label.setText("")
        self.refresh()

    def _sync_selected(self) -> None:
        coupon_id = self._selected_coupon_id()
        if coupon_id is None:
            self.status_label.setText("ابتدا یک کوپن را از فهرست انتخاب کنید.")
            return
        try:
            ecommerce_service.sync_coupon(coupon_id)
        except Exception as exc:  # noqa: BLE001 -- خطاهایِ StoreAPIError/شبکه متنوع‌اند
            self.status_label.setText(str(exc))
            self.refresh()
            return
        theme.set_status_label(self.status_label, "کوپن با فروشگاه سینک شد.", ok=True)
        self.refresh()

    def _delete_selected(self) -> None:
        coupon_id = self._selected_coupon_id()
        if coupon_id is None:
            self.status_label.setText("ابتدا یک کوپن را از فهرست انتخاب کنید.")
            return
        ecommerce_service.delete_coupon(coupon_id)
        self.status_label.setText("")
        self.refresh()
