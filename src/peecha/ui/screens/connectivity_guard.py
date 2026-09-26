"""نگهبانِ اتصال و بررسیِ سلامتِ سایت -- طبقِ ادامه‌یِ اولویت‌بندیِ بخشِ
عملیاتی: نمایِ یک‌جایِ سلامتِ همه‌یِ اتصال‌هایِ فروشگاهی/تلگرام/بله/
وردپرس، با رنگ‌آمیزیِ اتصال‌هایِ ناسالم (شکستِ پیاپیِ سینک/ارسال/انتشار)
+ دکمه‌یِ «بررسیِ سلامتِ الان» برایِ آزمایشِ فعالانه‌یِ همه‌یِ اتصال‌ها
بدونِ نیاز به منتظرِ تیکِ خودکارِ بعدی بودن."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
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
from peecha.services import connectivity_guard as guard_service
from peecha.ui import theme
from peecha.ui.widgets import LayoutEditMixin

_UNHEALTHY_THRESHOLD = 3
_TYPE_LABELS = {"ECOMMERCE": "فروشِ اینترنتی", "SOCIAL": "تلگرام/بله", "CMS": "سینکِ محتوا (CMS)"}


class ConnectivityGuardScreen(LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("نگهبانِ اتصال و سلامتِ سایت")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        info_label = QLabel("اتصال‌هایی که سه بار یا بیشتر پیاپی شکست خورده‌اند، ناسالم علامت‌گذاری می‌شوند.")
        info_label.setWordWrap(True)
        outer.addWidget(info_label)

        button_row = QHBoxLayout()
        refresh_button = QPushButton("🔄 بازآوری")
        refresh_button.clicked.connect(self.refresh)
        button_row.addWidget(refresh_button)
        health_check_button = QPushButton("🩺 بررسیِ سلامتِ الان")
        health_check_button.setObjectName("primaryIconButton")
        health_check_button.setToolTip("همینِ الان به همه‌یِ اتصال‌ها سر می‌زند -- بدونِ نیاز به منتظرِ تیکِ خودکارِ بعدی بودن")
        health_check_button.clicked.connect(self._run_health_check_now)
        button_row.addWidget(health_check_button)
        button_row.addStretch(1)
        outer.addLayout(button_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusError")
        outer.addWidget(self.status_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["نوع", "پلتفرم", "نام/آدرس", "شکستِ پیاپی", "آخرین خطا"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        outer.addWidget(self.table, stretch=1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def _fill_table(self, rows) -> None:
        self.table.setRowCount(len(rows))
        for row_index, r in enumerate(rows):
            is_unhealthy = r.consecutive_failure_count >= _UNHEALTHY_THRESHOLD
            values = [
                _TYPE_LABELS.get(r.connection_type, r.connection_type), r.platform_label, r.display_name,
                numerals.to_persian_digits(str(r.consecutive_failure_count)), r.last_error_message or "—",
            ]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if is_unhealthy:
                    cell.setForeground(QColor(theme.DANGER))
                self.table.setItem(row_index, col_index, cell)

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._fill_table(guard_service.list_all_connection_health(company_id))

    def _run_health_check_now(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        rows = guard_service.run_health_check_now(company_id)
        self._fill_table(rows)
        theme.set_status_label(self.status_label, "بررسیِ سلامتِ همه‌یِ اتصال‌ها انجام شد.", ok=True)
