"""دستیارِ فروشگاهِ اینترنتی -- طبقِ بازخوردِ صریحِ کاربر («امکاناتِ
حیاتیِ PeechaSync -- دستیارِ فروشگاهِ اینترنتی»): جمع‌بندیِ سلامتِ
اتصال + کاملیِ سئو + آمادگیِ عکسِ کالاها در یک فهرستِ اولویت‌بندی‌شده."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
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
from peecha.services import online_store_advisor as advisor_service
from peecha.ui import theme
from peecha.ui.widgets import LayoutEditMixin

_SEVERITY_LABELS = {"DANGER": "بحرانی", "WARNING": "هشدار"}


class _ScoreCard(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(title_label)
        self.value_label = QLabel("—")
        self.value_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        layout.addWidget(self.value_label)

    def set_score(self, score: int) -> None:
        self.value_label.setText(f"٪{score}" if score is not None else "—")
        if score >= 80:
            color = theme.SUCCESS
        elif score >= 50:
            color = theme.WARNING
        else:
            color = theme.DANGER
        self.value_label.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {color};")


class OnlineStoreAdvisorScreen(LayoutEditMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("دستیارِ فروشگاهِ اینترنتی")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        top_row = QHBoxLayout()
        self.connectivity_card = _ScoreCard("سلامتِ اتصال")
        top_row.addWidget(self.connectivity_card)
        self.seo_card = _ScoreCard("کاملیِ سئو")
        top_row.addWidget(self.seo_card)
        self.image_card = _ScoreCard("آمادگیِ عکسِ کالاها")
        top_row.addWidget(self.image_card)
        outer.addLayout(top_row)

        button_row = QHBoxLayout()
        refresh_button = QPushButton("🔄 بازآوری")
        refresh_button.clicked.connect(self.refresh)
        button_row.addWidget(refresh_button)
        button_row.addStretch(1)
        outer.addLayout(button_row)

        self.online_count_label = QLabel("")
        outer.addWidget(self.online_count_label)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["شدت", "مشکل", "راهنمایِ رفع"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        outer.addWidget(self.table, stretch=1)

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        summary = advisor_service.compute_advisor_summary(company_id)
        self.connectivity_card.set_score(summary.connectivity_score)
        self.seo_card.set_score(summary.seo_score)
        self.image_card.set_score(summary.image_score)
        self.online_count_label.setText(f"تعدادِ کالاهایِ منتشرشده در فروشگاه: {summary.online_item_count}")

        self.table.setRowCount(len(summary.issues))
        for row_index, issue in enumerate(summary.issues):
            values = [_SEVERITY_LABELS.get(issue.severity, issue.severity), issue.message, issue.fix_hint]
            for col_index, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col_index == 0 and issue.severity == "DANGER":
                    cell.setForeground(QColor(theme.DANGER))
                self.table.setItem(row_index, col_index, cell)
        if not summary.issues:
            self.table.setRowCount(1)
            ok_item = QTableWidgetItem("هیچ مشکلی یافت نشد -- فروشگاه در وضعیتِ خوبی است.")
            self.table.setItem(0, 0, QTableWidgetItem(""))
            self.table.setItem(0, 1, ok_item)
            self.table.setItem(0, 2, QTableWidgetItem(""))
