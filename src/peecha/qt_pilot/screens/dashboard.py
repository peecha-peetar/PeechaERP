"""داشبورد — معادلِ Qt برایِ dashboard.py/dashboard.kv در Kivy.

همان دلیلِ اصلی/چهار KPI/دو نمودار؛ فقط نمودارها با QtCharts (که RTL و
اعدادِ فارسی را هم به‌درستی نمایش می‌دهد) کشیده شده‌اند."""

from __future__ import annotations

from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QPieSeries, QValueAxis
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from peecha import session
from peecha.qt_pilot import theme
from peecha.services import dashboard as dashboard_service


class _KpiCard(QWidget):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(title_label)

        self.value_label = QLabel("۰")
        self.value_label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 26px; font-weight: bold;")
        layout.addWidget(self.value_label)

    def set_value(self, value: int) -> None:
        self.value_label.setText(_to_persian_digits(str(value)))


_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"


def _to_persian_digits(text: str) -> str:
    return "".join(_PERSIAN_DIGITS[int(ch)] if ch.isdigit() else ch for ch in text)


class DashboardScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        title = QLabel("داشبورد اصلی")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        subtitle = QLabel("خلاصه‌ی وضعیتِ سیستم")
        subtitle.setObjectName("sectionHint")
        outer.addWidget(subtitle)

        cards_layout = QGridLayout()
        cards_layout.setSpacing(16)
        self.card_companies = _KpiCard("شرکت‌ها")
        self.card_users = _KpiCard("کاربران")
        self.card_accounts = _KpiCard("حساب‌های کدینگ")
        self.card_entries = _KpiCard("اسنادِ حسابداری")
        for i, card in enumerate(
            (self.card_companies, self.card_users, self.card_accounts, self.card_entries)
        ):
            cards_layout.addWidget(card, 0, i)
        outer.addLayout(cards_layout)

        charts_layout = QGridLayout()
        charts_layout.setSpacing(16)

        self.entries_chart_view = self._build_chart_view()
        charts_layout.addWidget(self.entries_chart_view, 0, 0)

        self.donut_chart_view = self._build_chart_view()
        charts_layout.addWidget(self.donut_chart_view, 0, 1)

        outer.addLayout(charts_layout, stretch=1)

    def _build_chart_view(self) -> QChartView:
        chart = QChart()
        chart.legend().setVisible(False)
        view = QChartView(chart)
        view.setObjectName("card")
        view.setRenderHint(QPainter.Antialiasing)
        return view

    def refresh(self) -> None:
        company_id = session.current_company.company_id if session.current_company else None

        self.card_companies.set_value(dashboard_service.count_companies())
        self.card_users.set_value(dashboard_service.count_users())
        self.card_accounts.set_value(dashboard_service.count_chart_of_accounts(company_id))
        self.card_entries.set_value(dashboard_service.count_journal_entries(company_id))

        labels, values = dashboard_service.journal_entries_per_month(company_id)
        self._render_bar_chart(labels, values)

        breakdown = dashboard_service.chart_of_accounts_by_category(company_id)
        self._render_donut_chart(breakdown)

    def _render_bar_chart(self, labels: list[str], values: list[int]) -> None:
        chart = QChart()
        chart.setTitle("تعدادِ اسناد در ۶ ماهِ اخیر")
        chart.legend().setVisible(False)

        bar_set = QBarSet("تعداد اسناد")
        bar_set.append([float(v) for v in values])
        bar_set.setColor(QColor(theme.ACCENT))

        series = QBarSeries()
        series.append(bar_set)
        chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append(labels)
        chart.addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        max_value = max(values) if values else 1
        axis_y.setRange(0, max(max_value, 1))
        chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_y)

        self.entries_chart_view.setChart(chart)

    def _render_donut_chart(self, breakdown: list[tuple[str, int]]) -> None:
        chart = QChart()
        chart.setTitle("ترکیبِ کدینگِ حسابداری")

        series = QPieSeries()
        series.setHoleSize(0.45)
        for i, (label, count) in enumerate(breakdown):
            slice_ = series.append(f"{label} ({_to_persian_digits(str(count))})", float(count))
            slice_.setColor(QColor(theme.DONUT_COLORS[i % len(theme.DONUT_COLORS)]))
            slice_.setLabelVisible(False)

        chart.addSeries(series)
        chart.legend().setAlignment(Qt.AlignBottom)
        self.donut_chart_view.setChart(chart)
