"""پخشِ سرد/گرم -- R130: رصدِ ویزیت‌هایِ واقعی از دسکتاپ -- ثبتِ خودِ
چک‌این/چک‌اوت کارِ اپِ موبایل است (R132)، این صفحه فقط نمایش/فیلتر
می‌دهد (services/field_sales.py، R129)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import field_sales as field_sales_service
from peecha.services import users as users_service

_COLUMNS = ["وضعیت", "مشتری", "ویزیتور", "ساعتِ ورود", "ساعتِ خروج", "فاصله (متر)", "دلیلِ رد/یادداشت"]
_STATUS_LABELS = {"IN_PROGRESS": "درحالِ‌انجام", "COMPLETED": "انجام‌شده", "SKIPPED": "رد‌شده"}


class CustomerVisitsScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("ویزیت‌ها")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("ویزیتور"))
        self.visitor_combo = QComboBox()
        filters.addWidget(self.visitor_combo, stretch=1)
        filters.addWidget(QLabel("وضعیت"))
        self.status_combo = QComboBox()
        self.status_combo.addItem("(همه)", None)
        for code, label in _STATUS_LABELS.items():
            self.status_combo.addItem(label, code)
        filters.addWidget(self.status_combo, stretch=1)
        refresh_button = QPushButton("🔄")
        refresh_button.setObjectName("iconButton")
        refresh_button.setFixedWidth(44)
        refresh_button.setToolTip("به‌روزرسانی")
        refresh_button.clicked.connect(self._reload)
        filters.addWidget(refresh_button)
        outer.addLayout(filters)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        outer.addWidget(self.table, stretch=1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self.visitor_combo.clear()
        self.visitor_combo.addItem("(همه)", None)
        for u in users_service.list_users():
            self.visitor_combo.addItem(u.full_name, u.user_id)
        self._reload()

    def _reload(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        customers_by_id = {c["detail_account_id"]: c for c in dimensions_service.list_customers(company_id)}
        users_by_id = {u.user_id: u.full_name for u in users_service.list_users()}
        rows = field_sales_service.list_customer_visits(
            company_id, visitor_user_id=self.visitor_combo.currentData(), status_code=self.status_combo.currentData(),
        )
        self.table.setRowCount(len(rows))
        for row_index, r in enumerate(rows):
            customer = customers_by_id.get(r.customer_detail_account_id)
            note = r.skip_reason or r.notes or "—"
            values = [
                _STATUS_LABELS.get(r.status_code, r.status_code),
                f"{customer['code']} — {customer['name'] or ''}" if customer else str(r.customer_detail_account_id),
                users_by_id.get(r.visitor_user_id, "—"),
                r.checked_in_at.strftime("%Y-%m-%d %H:%M"),
                r.checked_out_at.strftime("%Y-%m-%d %H:%M") if r.checked_out_at else "—",
                f"{r.distance_from_customer_m:g}" if r.distance_from_customer_m is not None else "—",
                note,
            ]
            for col_index, value in enumerate(values):
                self.table.setItem(row_index, col_index, QTableWidgetItem(value))
