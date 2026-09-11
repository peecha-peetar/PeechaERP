"""بازاریابی و ارسالِ پیامکِ زمان‌بندی‌شده -- طبقِ درخواستِ صریحِ کاربر
(«یک تب برایِ بازاریابی و ارسالِ پیامکِ زمان‌بندی‌شده»). گیرندگانِ هر
کمپین از فهرستِ مشتریانِ اختصاص‌یافته به کاربرِ جاری (همان فهرستِ
فروشِ تلفنی، R135) عکس‌برداری می‌شوند؛ ارسالِ واقعی با تیکِ QTimerِ
shell_window.py (هم‌الگو با اتوسینکِ فروشِ اینترنتی/تقویمِ محتوایی)
هروقت زمانش برسد انجام می‌شود -- فقط تا وقتی برنامه باز است."""

from __future__ import annotations

import datetime

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session as app_session
from peecha.services import sms_marketing as sms_marketing_service
from peecha.ui.widgets import FieldGrid, FieldSpec, JalaliDateEdit

_COLUMNS = ["نام", "زمانِ ارسال", "وضعیت", "گیرندگان", "ارسال‌شده", "ناموفق"]

_STATUS_LABELS = {"PENDING": "درِ صف", "SENT": "ارسال‌شده", "FAILED": "ناموفق"}


class SmsMarketingScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("بازاریابی -- پیامکِ زمان‌بندی‌شده")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        hint = QLabel("گیرندگانِ هر کمپین، مشتریانِ اختصاص‌یافته به شما (همان فهرستِ فروشِ تلفنی) هستند.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        self.name_field = QLineEdit()
        self.message_field = QTextEdit()
        self.message_field.setFixedHeight(70)
        self.date_field = JalaliDateEdit()
        self.time_field = QTimeEdit()
        self.time_field.setDisplayFormat("HH:mm")

        form_grid = FieldGrid([
            FieldSpec("campaign_name", "نامِ کمپین", self.name_field, span=1),
            FieldSpec("campaign_date", "تاریخِ ارسال", self.date_field, span=1),
            FieldSpec("campaign_time", "ساعتِ ارسال", self.time_field, span=1),
            FieldSpec("campaign_message", "متنِ پیامک", self.message_field, span=3),
        ])
        outer.addWidget(form_grid)

        create_button = QPushButton("ایجادِ کمپین")
        create_button.setObjectName("primaryButton")
        create_button.clicked.connect(self._create_campaign)
        outer.addWidget(create_button)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusSuccess")
        outer.addWidget(self.status_label)

        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("کمپین‌هایِ ثبت‌شده:"))
        header_row.addStretch(1)
        refresh_button = QPushButton("🔄")
        refresh_button.setObjectName("iconButton")
        refresh_button.setFixedWidth(44)
        refresh_button.clicked.connect(self.refresh)
        header_row.addWidget(refresh_button)
        outer.addLayout(header_row)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        outer.addWidget(self.table, stretch=1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        campaigns = sms_marketing_service.list_campaigns(company_id)
        self.table.setRowCount(len(campaigns))
        for row_index, c in enumerate(campaigns):
            values = [
                c.name, numerals.format_jalali_datetime(c.scheduled_at), _STATUS_LABELS.get(c.status_code, c.status_code),
                str(c.recipient_count), str(c.sent_count), str(c.failed_count),
            ]
            for col_index, value in enumerate(values):
                self.table.setItem(row_index, col_index, QTableWidgetItem(numerals.to_persian_digits(value)))

    def _create_campaign(self) -> None:
        company_id = self._company_id()
        user = app_session.current_user
        if company_id is None or user is None:
            return
        name = self.name_field.text().strip()
        message_text = self.message_field.toPlainText().strip()
        scheduled_date = self.date_field.date()
        scheduled_time = self.time_field.time().toPython()
        scheduled_at = datetime.datetime.combine(scheduled_date, scheduled_time)
        try:
            sms_marketing_service.create_campaign(company_id, user.user_id, name, message_text, scheduled_at)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.status_label.setText("کمپین ثبت شد.")
        self.name_field.clear()
        self.message_field.clear()
        self.refresh()
