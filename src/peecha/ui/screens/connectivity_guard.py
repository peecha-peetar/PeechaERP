"""نگهبانِ اتصال -- طبقِ ادامه‌یِ اولویت‌بندیِ بخشِ عملیاتی: نمایِ
یک‌جایِ سلامتِ همه‌یِ اتصال‌هایِ فروشگاهی/تلگرام/بله، با رنگ‌آمیزیِ
اتصال‌هایِ ناسالم (شکستِ پیاپیِ سینک/ارسال) تا از حالتِ کاملاً بی‌صدایِ
قبلی خارج شود."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session as app_session
from peecha.services import connectivity_guard as guard_service
from peecha.ui import theme
from peecha.ui.widgets import LayoutEditMixin

_UNHEALTHY_THRESHOLD = 3


class ConnectivityGuardScreen(LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("نگهبانِ اتصال")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        info_label = QLabel("اتصال‌هایی که سه بار یا بیشتر پیاپی شکست خورده‌اند، ناسالم علامت‌گذاری می‌شوند.")
        info_label.setWordWrap(True)
        outer.addWidget(info_label)

        refresh_button = QPushButton("🔄 بازآوری")
        refresh_button.clicked.connect(self.refresh)
        outer.addWidget(refresh_button)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["نوع", "پلتفرم", "نام/آدرس", "شکستِ پیاپی", "آخرین خطا"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        outer.addWidget(self.table, stretch=1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        rows = guard_service.list_all_connection_health(company_id)
        self.table.setRowCount(len(rows))
        type_labels = {"ECOMMERCE": "فروشِ اینترنتی", "SOCIAL": "تلگرام/بله"}
        for row_index, r in enumerate(rows):
            is_unhealthy = r.consecutive_failure_count >= _UNHEALTHY_THRESHOLD
            values = [
                type_labels.get(r.connection_type, r.connection_type), r.platform_label, r.display_name,
                numerals.to_persian_digits(str(r.consecutive_failure_count)), r.last_error_message or "—",
            ]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if is_unhealthy:
                    cell.setForeground(QColor(theme.DANGER))
                self.table.setItem(row_index, col_index, cell)
