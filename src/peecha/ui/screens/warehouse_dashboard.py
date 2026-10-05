"""داشبوردِ انبار -- R246: ۲۳ شاخص و ۱۵ نمودار؛ کلیک رویِ هر کارت/نمودار گزارشِ مبدا را با همان بازه باز می‌کند."""

from __future__ import annotations

import decimal

from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QValueAxis
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGridLayout, QMessageBox, QPushButton

from peecha import numerals
from peecha.services import companies as companies_service
from peecha.services import warehouse_dashboard as dashboard_service
from peecha.ui import theme
from peecha.ui.screens.dashboard import _style_axis, _themed_chart, build_chart_card, render_donut_chart
from peecha.ui.screens.purchase_dashboards import _ClickableKpiCard, _ProcurementDashboardBase, format_kpi

_ICONS = {
    "VALUE": ("💰", "ACCENT"), "SKU": ("🏷", "CHART_PURPLE"), "IN_STOCK": ("📦", "CHART_TEAL"), "ZERO": ("⭕", "TEXT_SECONDARY"),
    "NEGATIVE": ("⚠", "DANGER"), "RESERVED": ("🔒", "CHART_ORANGE"), "FREE": ("✅", "SUCCESS"), "QUARANTINE": ("🧪", "WARNING"),
    "BLOCKED": ("⛔", "DANGER"), "CONSIGNMENT": ("🤝", "CHART_PURPLE"), "LOW": ("📉", "WARNING"), "ROP": ("🛒", "CHART_ORANGE"),
    "OVER": ("📈", "CHART_TEAL"), "DEAD": ("🪨", "DANGER"), "SLOW": ("🐢", "WARNING"), "FAST": ("⚡", "SUCCESS"),
    "NEAR_EXPIRY": ("⏳", "WARNING"), "EXPIRED": ("☠", "DANGER"), "OPEN_RECEIPTS": ("📥", "ACCENT"), "OPEN_ISSUES": ("📤", "ACCENT"),
    "TRANSFERS": ("🔁", "CHART_TEAL"), "COUNTS": ("🧮", "CHART_PURPLE"), "VARIANCE": ("≠", "DANGER"),
    "PUTAWAY": ("🧭", "CHART_ORANGE"), "PICKS": ("🧺", "ACCENT"), "COUNT_DUE": ("📅", "WARNING"),
}
_SERIES_COLORS = ("ACCENT", "CHART_ORANGE", "CHART_TEAL", "CHART_PURPLE")


def render_series_chart(chart_view, labels: list[str], series: dict[str, list]) -> None:
    """نمودارِ میله‌ایِ چندسری (ورود/خروج، آزاد/نقطهٔ سفارش، ...)."""
    chart = _themed_chart()
    bar_series = QBarSeries()
    bar_series.setBarWidth(0.6)
    top = 0.0
    lowest = 0.0
    for i, (name, values) in enumerate(series.items()):
        bar_set = QBarSet(name.replace("_", " "))
        bar_set.append([float(v or 0) for v in values])
        bar_set.setColor(QColor(getattr(theme, _SERIES_COLORS[i % len(_SERIES_COLORS)])))
        bar_series.append(bar_set)
        top = max([top] + [float(v or 0) for v in values])
        lowest = min([lowest] + [float(v or 0) for v in values])
    chart.addSeries(bar_series)
    chart.legend().setVisible(len(series) > 1)
    chart.legend().setAlignment(Qt.AlignBottom)
    axis_x = QBarCategoryAxis()
    axis_x.append([numerals.to_persian_digits(x) for x in labels] or [""])
    chart.addAxis(axis_x, Qt.AlignBottom)
    bar_series.attachAxis(axis_x)
    _style_axis(axis_x)
    axis_x.setGridLineVisible(False)
    axis_y = QValueAxis()
    axis_y.setRange(min(lowest, 0), max(top, 1))
    chart.addAxis(axis_y, Qt.AlignLeft)
    bar_series.attachAxis(axis_y)
    _style_axis(axis_y)
    chart_view.setChart(chart)


class WarehouseDashboard(_ProcurementDashboardBase):
    TITLE = "داشبوردِ انبار"

    def __init__(self, main_window=None) -> None:
        super().__init__(main_window)
        self.cards = {}
        self._kpis: dict[str, dashboard_service.Kpi] = {}
        self.chart_data: dict[str, dict] = {}
        grid = QGridLayout()
        grid.setSpacing(14)
        for i, (code, (icon, color)) in enumerate(_ICONS.items()):
            card = _ClickableKpiCard("", icon, getattr(theme, color), lambda c=code: self._open_kpi(c))
            self.cards[code] = card
            grid.addWidget(card, i // 5, i % 5)
        for col in range(5):
            grid.setColumnStretch(col, 1)
        self.body_layout.addLayout(grid)
        charts = QGridLayout()
        charts.setSpacing(16)
        self.chart_views = {}
        for i, (key, title, report_code, options) in enumerate(dashboard_service.CHART_TITLES):
            card, view = build_chart_card(title)
            view.setMinimumHeight(240)
            link = QPushButton("گزارش ←")
            link.setObjectName("flatButton")
            link.setCursor(Qt.PointingHandCursor)
            link.clicked.connect(lambda _c=False, r=report_code, o=options: self.open_report(r, o))
            card.layout().addWidget(link, alignment=Qt.AlignLeft)
            self.chart_views[key] = view
            charts.addWidget(card, i // 2, i % 2)
        self.body_layout.addLayout(charts)

    def open_report(self, report_code: str, options: dict | None = None) -> None:
        if self._main_window is None:
            return
        date_from, date_to = self.date_from.date(), self.date_to.date()
        self._main_window.open_screen(
            f"INV_RPT_{report_code}", then=lambda screen: screen.apply_preset(date_from, date_to, options or {}))

    def _open_kpi(self, code: str) -> None:
        kpi = self._kpis.get(code)
        if kpi is not None:
            self.open_report(kpi.report_code, kpi.options)

    def reload(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._decimal_places = companies_service.get_base_currency_decimal_places(company_id)
        from peecha.ui.screens import purchase_reports as report_screens

        if report_screens.BACKGROUND_REPORTS:
            self._generation = getattr(self, "_generation", 0) + 1
            worker = report_screens.ReportWorker(self._generation, dashboard_service.dashboard, company_id,
                                                 self.date_from.date(), self.date_to.date())
            worker.done.connect(self._on_worker_done)
            self._worker = worker
            worker.start()
            return
        self._apply(*dashboard_service.dashboard(company_id, self.date_from.date(), self.date_to.date()))

    def _on_worker_done(self, generation: int, result, error) -> None:
        if generation != getattr(self, "_generation", 0):
            return
        if error is not None:
            QMessageBox.warning(self, self.TITLE, f"بارگذاریِ داشبورد ناموفق بود:\n{error}")
            return
        self._apply(*result)

    def _apply(self, kpis, chart_data) -> None:
        self.chart_data = chart_data
        self._kpis = {k.code: k for k in kpis}
        for code, kpi in self._kpis.items():
            card = self.cards[code]
            card._title_label.setText(kpi.title)
            card.set_value(format_kpi(kpi.value, kpi.kind, self._decimal_places))
            card.setToolTip(f"فرمول: {kpi.formula}\nکلیک: گزارشِ مبدا")
        for key, data in self.chart_data.items():
            view = self.chart_views[key]
            if data["kind"] == "donut":
                values = next(iter(data["series"].values()), [])
                render_donut_chart(view, [(numerals.to_persian_digits(label), decimal.Decimal(v).quantize(decimal.Decimal(1)))
                                          for label, v in zip(data["labels"], values) if v and v > 0])
            else:
                render_series_chart(view, data["labels"], data["series"])
