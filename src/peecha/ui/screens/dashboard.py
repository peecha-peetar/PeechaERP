"""داشبورد — معادلِ Qt برایِ dashboard.py/dashboard.kv در Kivy.

همان دلیلِ اصلی/چهار KPI/دو نمودار؛ فقط نمودارها با QtCharts (که RTL و
اعدادِ فارسی را هم به‌درستی نمایش می‌دهد) کشیده شده‌اند.

بازطراحیِ «Peecha ERP 2026»: هر نمودار حالا درونِ یک کارتِ شیشه‌ایِ خودمان
جا می‌گیرد (تیترِ خودمان با تایپوگرافیِ یکدست، نه تیترِ بومیِ QChart) و
خودِ QChart با پس‌زمینه‌یِ شفاف + محور/افسانه‌یِ روشن برایِ زمینه‌یِ تیره
رنگ‌آمیزی شده — وگرنه با تمِ پیش‌فرضِ QtCharts (زمینه‌یِ سفید) رویِ اپِ
تیره یک مستطیلِ سفیدِ ناهماهنگ می‌شد."""

from __future__ import annotations

from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QPieSeries, QValueAxis
from PySide6.QtCore import Qt, QMargins
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from peecha import session
from peecha.ui import theme
from peecha.ui.widgets import KpiCard
from peecha.services import dashboard as dashboard_service


class _KpiCard(KpiCard):
    def set_value(self, value: int) -> None:
        super().set_value(_to_persian_digits(str(value)))


_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"


def _to_persian_digits(text: str) -> str:
    return "".join(_PERSIAN_DIGITS[int(ch)] if ch.isdigit() else ch for ch in text)


class DashboardScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 32, 32, 32)
        outer.setSpacing(24)

        title = QLabel("داشبورد اصلی")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        subtitle = QLabel("خلاصه‌ی وضعیتِ سیستم")
        subtitle.setObjectName("sectionHint")
        outer.addWidget(subtitle)

        cards_layout = QGridLayout()
        cards_layout.setSpacing(16)
        self.card_companies = _KpiCard("شرکت‌ها", "🏢", theme.ACCENT)
        self.card_users = _KpiCard("کاربران", "👥", theme.CHART_TEAL)
        self.card_accounts = _KpiCard("حساب‌های کدینگ", "📚", theme.CHART_PURPLE)
        self.card_entries = _KpiCard("اسنادِ حسابداری", "🧾", theme.WARNING)
        for i, card in enumerate(
            (self.card_companies, self.card_users, self.card_accounts, self.card_entries)
        ):
            cards_layout.addWidget(card, 0, i)
            cards_layout.setColumnStretch(i, 1)
        outer.addLayout(cards_layout)

        charts_layout = QGridLayout()
        charts_layout.setSpacing(16)
        charts_layout.setColumnStretch(0, 1)
        charts_layout.setColumnStretch(1, 1)

        entries_card, self.entries_chart_view = self._build_chart_card("تعدادِ اسناد در ۶ ماهِ اخیر")
        charts_layout.addWidget(entries_card, 0, 0)

        donut_card, self.donut_chart_view = self._build_chart_card("ترکیبِ کدینگِ حسابداری")
        charts_layout.addWidget(donut_card, 0, 1)

        outer.addLayout(charts_layout, stretch=1)

    def _build_chart_card(self, title_text: str) -> tuple[QWidget, QChartView]:
        """کارتِ شیشه‌ایِ خودمان دورِ نمودار — تیتر با تایپوگرافیِ یکدستِ
        برنامه (نه تیترِ بومیِ QChart)، و QChartView بدونِ بردر/پس‌زمینه‌یِ
        خودش تا کاملاً درونِ همین کارت شناور به‌نظر برسد."""
        card = QWidget()
        card.setObjectName("card")
        card.setMinimumHeight(320)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title_label = QLabel(title_text)
        title_label.setObjectName("cardTitle")
        layout.addWidget(title_label)

        chart = QChart()
        chart.legend().setVisible(False)
        chart.setBackgroundVisible(False)
        chart.setMargins(QMargins(4, 4, 4, 4))

        view = QChartView(chart)
        view.setStyleSheet("background: transparent; border: none;")
        view.setRenderHint(QPainter.Antialiasing)
        layout.addWidget(view, stretch=1)
        return card, view

    def refresh(self) -> None:
        company_id = session.current_company.company_id if session.current_company else None

        # طبقِ باگِ واقعیِ کشف‌شده (سوییچِ روشن/تیره): KpiCard رنگ‌هایش را
        # در __init__ منجمد می‌کند — چون این صفحه singleton است (بازسازی
        # نمی‌شود)، هر بار refresh (که بعدِ سوییچِ تم هم صدا زده می‌شود)
        # باید صریحاً رنگ‌هایِ تازه‌یِ تم را به کارت‌ها اعمال کند.
        self.card_companies.refresh_theme(theme.ACCENT)
        self.card_users.refresh_theme(theme.CHART_TEAL)
        self.card_accounts.refresh_theme(theme.CHART_PURPLE)
        self.card_entries.refresh_theme(theme.WARNING)

        self.card_companies.set_value(dashboard_service.count_companies())
        self.card_users.set_value(dashboard_service.count_users())
        self.card_accounts.set_value(dashboard_service.count_chart_of_accounts(company_id))
        self.card_entries.set_value(dashboard_service.count_journal_entries(company_id))

        labels, values = dashboard_service.journal_entries_per_month(company_id)
        self._render_bar_chart(labels, values)

        breakdown = dashboard_service.chart_of_accounts_by_category(company_id)
        self._render_donut_chart(breakdown)

    def _themed_chart(self) -> QChart:
        chart = QChart()
        chart.legend().setVisible(False)
        chart.setBackgroundVisible(False)
        return chart

    def _style_axis(self, axis) -> None:
        axis.setLabelsColor(QColor(theme.TEXT_SECONDARY))
        axis.setLinePen(QPen(QColor(theme.DIVIDER)))
        axis.setGridLineColor(QColor(theme.DIVIDER))
        label_font = QFont()
        label_font.setPointSize(9)
        axis.setLabelsFont(label_font)

    def _render_bar_chart(self, labels: list[str], values: list[int]) -> None:
        chart = self._themed_chart()

        bar_set = QBarSet("تعداد اسناد")
        bar_set.append([float(v) for v in values])
        bar_set.setColor(QColor(theme.ACCENT))
        bar_set.setBorderColor(QColor(theme.ACCENT_HOVER))

        series = QBarSeries()
        series.setBarWidth(0.55)
        series.append(bar_set)
        chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append(labels)
        chart.addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)
        self._style_axis(axis_x)
        axis_x.setGridLineVisible(False)

        axis_y = QValueAxis()
        max_value = max(values) if values else 1
        axis_y.setRange(0, max(max_value, 1))
        chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_y)
        self._style_axis(axis_y)

        self.entries_chart_view.setChart(chart)

    def _render_donut_chart(self, breakdown: list[tuple[str, int]]) -> None:
        chart = self._themed_chart()
        chart.legend().setVisible(True)

        series = QPieSeries()
        series.setHoleSize(0.55)
        for i, (label, count) in enumerate(breakdown):
            slice_ = series.append(f"{label} ({_to_persian_digits(str(count))})", float(count))
            color = QColor(theme.DONUT_COLORS[i % len(theme.DONUT_COLORS)])
            slice_.setColor(color)
            slice_.setBorderColor(QColor(theme.SURFACE))
            slice_.setBorderWidth(2)
            slice_.setLabelVisible(False)

        chart.addSeries(series)
        chart.legend().setAlignment(Qt.AlignBottom)
        chart.legend().setLabelColor(QColor(theme.TEXT_SECONDARY))
        legend_font = QFont()
        legend_font.setPointSize(9)
        chart.legend().setFont(legend_font)
        self.donut_chart_view.setChart(chart)
