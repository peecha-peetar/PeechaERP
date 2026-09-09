"""پستِ خودکار در تلگرام/بله + تقویمِ محتوایی (طبقِ درخواستِ صریحِ کاربر)."""

from __future__ import annotations

import datetime

from PySide6.QtCore import QTime, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.services import commercial_social as social_service
from peecha.ui import theme
from peecha.ui.widgets import JalaliDateEdit, LayoutEditMixin, wrap_scrollable

_PLATFORM_LABELS = {"TELEGRAM": "تلگرام", "BALE": "بله"}
_POST_STATUS_LABELS = {"SCHEDULED": "زمان‌بندی‌شده", "SENT": "ارسال‌شده", "FAILED": "ناموفق", "CANCELED": "لغوشده"}


class CommercialSocialScreen(LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._connections: list = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("پستِ خودکار و تقویمِ محتوا")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._build_connections_tab(), "اتصالاتِ تلگرام/بله")
        tabs.addTab(self._build_calendar_tab(), "تقویمِ محتوا")
        outer.addWidget(tabs, stretch=1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    # --- اتصالات -----------------------------------------------------------
    def _build_connections_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)

        self.connections_table = QTableWidget(0, 3)
        self.connections_table.setHorizontalHeaderLabels(["پلتفرم", "نام", "شناسه‌یِ چت"])
        self.connections_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.connections_table.verticalHeader().setVisible(False)
        self.connections_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.connections_table.cellClicked.connect(self._on_connection_selected)
        outer.addWidget(self.connections_table, stretch=1)

        form = QHBoxLayout()
        self.social_platform_combo = QComboBox()
        for code, label in _PLATFORM_LABELS.items():
            self.social_platform_combo.addItem(label, code)
        form.addWidget(self.social_platform_combo)
        self.social_name_field = QLineEdit()
        self.social_name_field.setPlaceholderText("نامِ نمایشی (مثلاً «کانالِ فروشگاه»)")
        form.addWidget(self.social_name_field, stretch=1)
        self.social_chat_id_field = QLineEdit()
        self.social_chat_id_field.setPlaceholderText("شناسه‌یِ چت/کانال")
        form.addWidget(self.social_chat_id_field)
        self.social_token_field = QLineEdit()
        self.social_token_field.setPlaceholderText("توکنِ بات")
        self.social_token_field.setEchoMode(QLineEdit.Password)
        form.addWidget(self.social_token_field)
        add_connection_button = QPushButton("➕")
        add_connection_button.setObjectName("primaryIconButton")
        add_connection_button.setFixedWidth(44)
        add_connection_button.setToolTip("افزودنِ اتصال")
        add_connection_button.clicked.connect(self._add_connection)
        form.addWidget(add_connection_button)
        test_connection_button = QPushButton("🔎")
        test_connection_button.setObjectName("iconButton")
        test_connection_button.setFixedWidth(44)
        test_connection_button.setToolTip("آزمایشِ اتصالِ انتخاب‌شده")
        test_connection_button.clicked.connect(self._test_connection)
        form.addWidget(test_connection_button)
        outer.addLayout(form)

        self.social_status_label = QLabel("")
        self.social_status_label.setObjectName("statusError")
        outer.addWidget(self.social_status_label)
        return wrap_scrollable(page)

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._connections = social_service.list_connections(company_id)
        self.connections_table.setRowCount(len(self._connections))
        for row_index, c in enumerate(self._connections):
            values = [_PLATFORM_LABELS.get(c.platform_code, c.platform_code), c.display_name, c.chat_id]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, c.connection_id)
                self.connections_table.setItem(row_index, col_index, cell)

        self.post_connection_combo.clear()
        for c in self._connections:
            self.post_connection_combo.addItem(f"{_PLATFORM_LABELS.get(c.platform_code, c.platform_code)} — {c.display_name}", c.connection_id)

        self._refresh_calendar()

    def _on_connection_selected(self, row: int, _column: int) -> None:
        self._selected_connection_id = self.connections_table.item(row, 0).data(Qt.UserRole)

    def _add_connection(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        try:
            social_service.create_connection(
                company_id, self.social_platform_combo.currentData(), self.social_name_field.text(),
                self.social_chat_id_field.text(), self.social_token_field.text(),
            )
        except ValueError as exc:
            self.social_status_label.setText(str(exc))
            return
        self.social_name_field.clear()
        self.social_chat_id_field.clear()
        self.social_token_field.clear()
        self.social_status_label.setText("")
        self.refresh()

    def _test_connection(self) -> None:
        connection_id = getattr(self, "_selected_connection_id", None)
        if connection_id is None:
            self.social_status_label.setText("ابتدا یک اتصال را از فهرست انتخاب کنید.")
            return
        try:
            ok, message = social_service.test_connection(connection_id)
        except ValueError as exc:
            self.social_status_label.setText(str(exc))
            return
        theme.set_status_label(self.social_status_label, message, ok=ok)

    # --- تقویمِ محتوا --------------------------------------------------------
    def _build_calendar_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)

        self.calendar_table = QTableWidget(0, 6)
        self.calendar_table.setHorizontalHeaderLabels(["تاریخ/ساعت", "اتصال", "عنوان", "وضعیت", "خطا", ""])
        self.calendar_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.calendar_table.verticalHeader().setVisible(False)
        self.calendar_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        outer.addWidget(self.calendar_table, stretch=1)

        form = QHBoxLayout()
        self.post_connection_combo = QComboBox()
        form.addWidget(self.post_connection_combo)
        self.post_date_field = JalaliDateEdit()
        form.addWidget(self.post_date_field)
        self.post_time_field = QTimeEdit()
        self.post_time_field.setDisplayFormat("HH:mm")
        self.post_time_field.setTime(QTime.currentTime())
        form.addWidget(self.post_time_field)
        add_post_button = QPushButton("➕")
        add_post_button.setObjectName("primaryIconButton")
        add_post_button.setFixedWidth(44)
        add_post_button.setToolTip("افزودنِ پست به تقویم")
        add_post_button.clicked.connect(self._add_post)
        form.addWidget(add_post_button)
        outer.addLayout(form)

        self.post_title_field = QLineEdit()
        self.post_title_field.setPlaceholderText("عنوانِ پست (اختیاری)")
        outer.addWidget(self.post_title_field)
        self.post_body_field = QPlainTextEdit()
        self.post_body_field.setPlaceholderText("متنِ پست")
        self.post_body_field.setFixedHeight(80)
        outer.addWidget(self.post_body_field)

        self.calendar_status_label = QLabel("")
        self.calendar_status_label.setObjectName("statusError")
        outer.addWidget(self.calendar_status_label)
        return wrap_scrollable(page)

    def _refresh_calendar(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        connections_by_id = {c.connection_id: c for c in self._connections}
        posts = social_service.list_posts(company_id)
        self.calendar_table.setRowCount(len(posts))
        for row_index, post in enumerate(posts):
            connection = connections_by_id.get(post.connection_id)
            connection_label = f"{_PLATFORM_LABELS.get(connection.platform_code, connection.platform_code)} — {connection.display_name}" if connection else str(post.connection_id)
            values = [
                post.scheduled_at.strftime("%Y-%m-%d %H:%M"), connection_label, post.title or "",
                _POST_STATUS_LABELS.get(post.status_code, post.status_code), post.error_message or "",
            ]
            for col_index, value in enumerate(values):
                self.calendar_table.setItem(row_index, col_index, QTableWidgetItem(value))
            if post.status_code == "SCHEDULED":
                send_now_button = QPushButton("📤")
                send_now_button.setObjectName("primaryIconButton")
                send_now_button.setToolTip("ارسالِ الان")
                send_now_button.clicked.connect(lambda _checked=False, post_id=post.post_id: self._send_post_now(post_id))
                self.calendar_table.setCellWidget(row_index, 5, send_now_button)

    def _add_post(self) -> None:
        company_id = self._company_id()
        connection_id = self.post_connection_combo.currentData()
        if company_id is None or connection_id is None:
            self.calendar_status_label.setText("ابتدا یک اتصال انتخاب کنید.")
            return
        picked_time = self.post_time_field.time()
        scheduled_at = datetime.datetime.combine(self.post_date_field.date(), datetime.time(picked_time.hour(), picked_time.minute()))
        try:
            social_service.create_post(company_id, connection_id, self.post_title_field.text(), self.post_body_field.toPlainText(), scheduled_at)
        except ValueError as exc:
            self.calendar_status_label.setText(str(exc))
            return
        self.post_title_field.clear()
        self.post_body_field.clear()
        self.calendar_status_label.setText("")
        self._refresh_calendar()

    def _send_post_now(self, post_id: int) -> None:
        try:
            social_service.send_post_now(post_id)
        except Exception as exc:  # noqa: BLE001
            self.calendar_status_label.setText(str(exc))
            self._refresh_calendar()
            return
        theme.set_status_label(self.calendar_status_label, "پست ارسال شد.", ok=True)
        self._refresh_calendar()
