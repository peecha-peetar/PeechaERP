"""داشبوردِ سرپرست -- R134، آخرین فازِ ماژولِ پخشِ سرد/گرم. طبقِ الزامِ
قدیمیِ کاربر («منوها شلوغ نشه»)، این صفحه یک تبِ جدید در همان
commercial_distribution_hub.py است، نه یک آیتمِ جدیدِ منو.

چهار بخش: پوششِ ویزیتِ امروز (یک روزِ مشخص، چون برنامهٔ مراجعه هفتگی
است)، عملکردِ فروشِ هر ویزیتور (بازه)، فاکتورهایِ پخشِ گرمِ بدونِ رسیدِ
تحویل (هشدار -- طبقِ تصمیمِ R133 که رسیدِ تحویل جایگزینِ تاییدِ مدیر
شده)، و کسریِ بارگیریِ خودرو (بازه)."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from peecha import session as app_session
from peecha.services import field_sales_dashboard as dashboard_service
from peecha.ui import theme
from peecha.ui.widgets import JalaliDateEdit


def _amount_item(value) -> QTableWidgetItem:
    return QTableWidgetItem(f"{value:,.0f}")


class FieldSalesDashboardScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(10)

        title = QLabel("داشبوردِ سرپرست")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("پوششِ ویزیتِ روزِ:"))
        self.coverage_date = JalaliDateEdit()
        filters.addWidget(self.coverage_date)
        filters.addSpacing(16)
        filters.addWidget(QLabel("بازهٔ فروش/تحویل/بارگیری از:"))
        self.date_from = JalaliDateEdit()
        filters.addWidget(self.date_from)
        filters.addWidget(QLabel("تا:"))
        self.date_to = JalaliDateEdit()
        filters.addWidget(self.date_to)
        refresh_button = QPushButton("🔄 به‌روزرسانی")
        refresh_button.clicked.connect(self.refresh)
        filters.addWidget(refresh_button)
        filters.addStretch(1)
        outer.addLayout(filters)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        self._sections_layout = QVBoxLayout(container)
        self._sections_layout.setSpacing(18)
        scroll.setWidget(container)
        outer.addWidget(scroll, stretch=1)

        self.coverage_table = self._add_section(
            "پوششِ ویزیتِ امروز", ["ویزیتور", "برنامه‌ریزی‌شده", "انجام‌شده", "ردشده", "درحالِ‌انجام", "دیده‌نشده", "درصدِ پوشش"],
        )
        self.performance_table = self._add_section(
            "عملکردِ فروشِ ویزیتورها", ["ویزیتور", "تعدادِ سفارشِ سرد", "مبلغِ سفارشِ سرد", "تعدادِ فاکتورِ گرم", "مبلغِ فاکتورِ گرم"],
        )
        self.compliance_table = self._add_section(
            "فاکتورهایِ پخشِ گرمِ بدونِ رسیدِ تحویل", ["شمارهٔ سند", "تاریخ", "مشتری", "مبلغ", "ویزیتور"],
        )
        self.loading_table = self._add_section(
            "کسریِ بارگیریِ خودرو", ["خودرو", "تاریخِ بارگیری", "تعدادِ اقلامِ کسری", "جمعِ مقدارِ کسری"],
        )
        self._sections_layout.addStretch(1)

    def _add_section(self, title_text: str, columns: list[str]) -> QTableWidget:
        section_title = QLabel(title_text)
        section_title.setObjectName("sectionTitle")
        self._sections_layout.addWidget(section_title)
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.setMinimumHeight(140)
        self._sections_layout.addWidget(table)
        return table

    def _company_id(self) -> int | None:
        return app_session.current_company.company_id if app_session.current_company else None

    def refresh(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._reload_coverage(company_id)
        self._reload_performance(company_id)
        self._reload_compliance(company_id)
        self._reload_loading(company_id)

    def _reload_coverage(self, company_id: int) -> None:
        rows = dashboard_service.compute_visit_coverage(company_id, self.coverage_date.date())
        self.coverage_table.setRowCount(len(rows))
        for row_index, r in enumerate(rows):
            values = [r.visitor_name, str(r.planned_count), str(r.completed_count), str(r.skipped_count), str(r.in_progress_count), str(r.not_visited_count)]
            for col_index, value in enumerate(values):
                self.coverage_table.setItem(row_index, col_index, QTableWidgetItem(value))
            rate_item = QTableWidgetItem(f"٪{r.completion_rate_percent}")
            if r.not_visited_count > 0:
                rate_item.setForeground(QColor(theme.DANGER))
            elif r.completion_rate_percent >= 100:
                rate_item.setForeground(QColor(theme.SUCCESS))
            self.coverage_table.setItem(row_index, 6, rate_item)

    def _reload_performance(self, company_id: int) -> None:
        rows = dashboard_service.compute_visitor_performance(company_id, self.date_from.date(), self.date_to.date())
        self.performance_table.setRowCount(len(rows))
        for row_index, r in enumerate(rows):
            self.performance_table.setItem(row_index, 0, QTableWidgetItem(r.visitor_name))
            self.performance_table.setItem(row_index, 1, QTableWidgetItem(str(r.pre_sales_order_count)))
            self.performance_table.setItem(row_index, 2, _amount_item(r.pre_sales_order_amount))
            self.performance_table.setItem(row_index, 3, QTableWidgetItem(str(r.van_sales_invoice_count)))
            self.performance_table.setItem(row_index, 4, _amount_item(r.van_sales_invoice_amount))

    def _reload_compliance(self, company_id: int) -> None:
        rows = dashboard_service.compute_delivery_compliance(company_id, self.date_from.date(), self.date_to.date())
        self.compliance_table.setRowCount(len(rows))
        for row_index, r in enumerate(rows):
            values = [str(r.document_no), r.document_date.isoformat(), r.customer_label]
            for col_index, value in enumerate(values):
                self.compliance_table.setItem(row_index, col_index, QTableWidgetItem(value))
            self.compliance_table.setItem(row_index, 3, _amount_item(r.total_amount))
            visitor_item = QTableWidgetItem(r.visitor_name)
            visitor_item.setForeground(QColor(theme.DANGER))
            self.compliance_table.setItem(row_index, 4, visitor_item)

    def _reload_loading(self, company_id: int) -> None:
        rows = dashboard_service.compute_vehicle_loading_variance(company_id, self.date_from.date(), self.date_to.date())
        self.loading_table.setRowCount(len(rows))
        for row_index, r in enumerate(rows):
            self.loading_table.setItem(row_index, 0, QTableWidgetItem(r.vehicle_warehouse_label))
            self.loading_table.setItem(row_index, 1, QTableWidgetItem(r.loading_date.isoformat()))
            self.loading_table.setItem(row_index, 2, QTableWidgetItem(str(r.item_count_short)))
            self.loading_table.setItem(row_index, 3, _amount_item(r.total_shortage_quantity))
