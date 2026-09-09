"""مدیریتِ نظرات/امتیازِ مشتریان -- طبقِ بازخوردِ صریحِ کاربر («امکاناتِ
حیاتیِ PeechaSync -- مدیریتِ نظرات/امتیازِ مشتریان»): نظراتِ زنده از
فروشگاهِ ووکامرس خوانده می‌شود (بدونِ ذخیره‌یِ محلی) و تایید/رد/حذف
مستقیماً رویِ همان فروشگاه اِعمال می‌شود."""

from __future__ import annotations

from PySide6.QtCore import Qt
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
from peecha.services import commercial_ecommerce as ecommerce_service
from peecha.ui import theme
from peecha.ui.widgets import LayoutEditMixin

_STATUS_LABELS = {"approved": "تاییدشده", "hold": "درانتظارِ تایید", "spam": "اسپم", "trash": "زباله‌دان"}


class CommercialReviewsScreen(LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._connections: list = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("نظرات و امتیازِ مشتریان")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        top_row = QHBoxLayout()
        self.connection_combo = QComboBox()
        self.connection_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        top_row.addWidget(self.connection_combo, stretch=1)
        refresh_button = QPushButton("🔄 بازآوری")
        refresh_button.clicked.connect(self.refresh)
        top_row.addWidget(refresh_button)
        outer.addLayout(top_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        outer.addWidget(self.status_label)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["محصول", "کاربر", "متنِ نظر", "امتیاز", "وضعیت", ""])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        outer.addWidget(self.table, stretch=1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        previous_connection_id = self.connection_combo.currentData()
        self._connections = [
            c for c in ecommerce_service.list_connections(company_id)
            if c.platform_code == "WOOCOMMERCE" and c.sync_status == "ACTIVE"
        ]
        self.connection_combo.blockSignals(True)
        self.connection_combo.clear()
        for c in self._connections:
            self.connection_combo.addItem(c.store_url, c.connection_id)
        if previous_connection_id is not None:
            index = self.connection_combo.findData(previous_connection_id)
            if index >= 0:
                self.connection_combo.setCurrentIndex(index)
        self.connection_combo.blockSignals(False)

        connection_id = self.connection_combo.currentData()
        if connection_id is None:
            self.table.setRowCount(0)
            return
        try:
            reviews = ecommerce_service.list_reviews(connection_id)
        except Exception as exc:  # noqa: BLE001 -- خطاهایِ StoreAPIError/شبکه متنوع‌اند
            self.status_label.setText(str(exc))
            self.table.setRowCount(0)
            return
        self.status_label.setText("")
        self.table.setRowCount(len(reviews))
        for row_index, review in enumerate(reviews):
            values = [review.product_name, review.reviewer, review.review, "★" * review.rating, _STATUS_LABELS.get(review.status, review.status)]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col_index == 0:
                    cell.setData(Qt.UserRole, review.external_review_id)
                self.table.setItem(row_index, col_index, cell)

            actions = QHBoxLayout()
            actions_widget = QWidget()
            actions_widget.setLayout(actions)
            approve_button = QPushButton("✅")
            approve_button.setToolTip("تایید")
            approve_button.clicked.connect(lambda _checked=False, rid=review.external_review_id: self._approve(rid))
            actions.addWidget(approve_button)
            reject_button = QPushButton("⛔")
            reject_button.setToolTip("درانتظارِ تایید")
            reject_button.clicked.connect(lambda _checked=False, rid=review.external_review_id: self._reject(rid))
            actions.addWidget(reject_button)
            delete_button = QPushButton("🗑")
            delete_button.setToolTip("حذف")
            delete_button.clicked.connect(lambda _checked=False, rid=review.external_review_id: self._delete(rid))
            actions.addWidget(delete_button)
            actions.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(row_index, 5, actions_widget)

    def _approve(self, external_review_id: str) -> None:
        connection_id = self.connection_combo.currentData()
        try:
            ecommerce_service.approve_review(connection_id, external_review_id)
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(str(exc))
            return
        theme.set_status_label(self.status_label, "نظر تایید شد.", ok=True)
        self.refresh()

    def _reject(self, external_review_id: str) -> None:
        connection_id = self.connection_combo.currentData()
        try:
            ecommerce_service.reject_review(connection_id, external_review_id)
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(str(exc))
            return
        theme.set_status_label(self.status_label, "نظر به حالتِ درانتظار برگشت.", ok=True)
        self.refresh()

    def _delete(self, external_review_id: str) -> None:
        connection_id = self.connection_combo.currentData()
        try:
            ecommerce_service.delete_review(connection_id, external_review_id)
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("")
        self.refresh()
