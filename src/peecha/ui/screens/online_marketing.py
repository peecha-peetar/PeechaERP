"""مدیریتِ بازاریابیِ فروشگاهِ اینترنتی -- طبقِ بازخوردِ صریحِ کاربر
(«امکاناتِ حیاتیِ PeechaSync -- مدیریتِ بازاریابی»): فهرستِ کالاهایِ
منتشرشده در فروشگاه با فروشِ واقعی/موجودی/پیشنهادِ اقدام، به‌علاوهٔ
یادآوریِ تقویمِ مناسبتی."""

from __future__ import annotations

import datetime

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import numerals, session as app_session
from peecha.services import online_marketing as marketing_service
from peecha.ui.widgets import JalaliDateEdit, LayoutEditMixin


class OnlineMarketingScreen(LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("مدیریتِ بازاریابیِ فروشگاهِ اینترنتی")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("از تاریخ:"))
        self.date_from_field = JalaliDateEdit()
        self.date_from_field.setDate(datetime.date.today() - datetime.timedelta(days=30))
        filter_row.addWidget(self.date_from_field)
        filter_row.addWidget(QLabel("تا تاریخ:"))
        self.date_to_field = JalaliDateEdit()
        self.date_to_field.setDate(datetime.date.today())
        filter_row.addWidget(self.date_to_field)
        refresh_button = QPushButton("🔄 بازآوری")
        refresh_button.clicked.connect(self.refresh)
        filter_row.addWidget(refresh_button)
        filter_row.addStretch(1)
        outer.addLayout(filter_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["کالا", "موجودی", "تعدادِ فروخته‌شده", "فروشِ خالص", "پیشنهادِ اقدام"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        outer.addWidget(self.table, stretch=1)

        occasions_title = QLabel("یادآوریِ تقویمِ مناسبتیِ فروشگاهی")
        occasions_title.setStyleSheet("font-weight: bold;")
        outer.addWidget(occasions_title)
        self.occasions_list = QListWidget()
        self.occasions_list.setMaximumHeight(90)
        outer.addWidget(self.occasions_list)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        rows = marketing_service.compute_marketing_overview(
            company_id, self.date_from_field.date(), self.date_to_field.date(),
        )
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                f"{row.item_code} — {row.item_name}",
                numerals.format_money(row.stock_available, 2),
                numerals.format_money(row.quantity_sold, 2),
                numerals.format_money(row.net_revenue, 0),
                row.suggested_action,
            ]
            for col_index, value in enumerate(values):
                self.table.setItem(row_index, col_index, QTableWidgetItem(value))

        self.occasions_list.clear()
        for occasion in marketing_service.upcoming_occasions():
            when = "همین ماه" if occasion.months_away == 0 else f"{numerals.to_persian_digits(str(occasion.months_away))} ماهِ دیگر"
            item = QListWidgetItem(f"🎉 {occasion.name} ({when}) -- {occasion.note}")
            self.occasions_list.addItem(item)
