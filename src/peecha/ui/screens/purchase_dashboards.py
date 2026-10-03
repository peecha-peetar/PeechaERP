"""داشبوردِ مدیریتیِ خرید و داشبوردِ استثناهایِ خرید -- R239.

هر کارت/ردیف از services/purchase_dashboard می‌آید و با کلیک، همان گزارشِ مبدا
با همان بازهٔ تاریخ و گزینه‌ها باز می‌شود (Drill-down)."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from peecha import numerals, session
from peecha.services import companies as companies_service
from peecha.services import purchase_dashboard as dashboard_service
from peecha.ui import theme
from peecha.ui.screens.dashboard import build_chart_card, render_bar_chart, render_donut_chart
from peecha.ui.widgets import JalaliDateEdit, KpiCard

_KPI_ICONS = {
    "NET": ("🛒", "ACCENT"), "INVOICES": ("🧾", "CHART_PURPLE"), "SUPPLIERS": ("🏭", "CHART_TEAL"),
    "OPEN_PO": ("📦", "CHART_ORANGE"), "GRIR": ("📥", "WARNING"), "PAYABLE": ("💳", "ACCENT"),
    "OVERDUE": ("⏰", "DANGER"), "OTD": ("🚚", "SUCCESS"), "RETURN_RATE": ("↩", "WARNING"),
    "PPV": ("💹", "CHART_PURPLE"), "CYCLE": ("⏱", "CHART_TEAL"), "APPROVALS": ("✅", "CHART_ORANGE"),
}
_SEVERITY_COLOR = {"HIGH": "DANGER", "MEDIUM": "WARNING", "LOW": "TEXT_SECONDARY"}


def format_kpi(value, kind: str, decimal_places: int = 0) -> str:
    if value is None:
        return "—"
    if kind == "MONEY":
        return numerals.format_money(decimal.Decimal(value), decimal_places, None)
    if kind == "PERCENT":
        return f"{numerals.format_money(decimal.Decimal(value), 1, None)}٪"
    if kind == "DAYS":
        return f"{numerals.to_persian_digits(str(value))} روز"
    return numerals.to_persian_digits(str(value))


class _ClickableKpiCard(KpiCard):
    def __init__(self, title: str, icon: str, color: str, on_click) -> None:
        super().__init__(title, icon, color)
        self._on_click = on_click
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._on_click()
        super().mouseReleaseEvent(event)


class _ProcurementDashboardBase(QWidget):
    TITLE = ""

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self._decimal_places = 0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        header = QHBoxLayout()
        title = QLabel(self.TITLE)
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(QLabel("از تاریخ:"))
        self.date_from = JalaliDateEdit()
        header.addWidget(self.date_from)
        header.addWidget(QLabel("تا تاریخ:"))
        self.date_to = JalaliDateEdit()
        header.addWidget(self.date_to)
        apply_button = QPushButton("به‌روزرسانی")
        apply_button.setObjectName("primaryButton")
        apply_button.clicked.connect(self.reload)
        header.addWidget(apply_button)
        outer.addLayout(header)
        hint = QLabel("روی هر کارت/ردیف کلیک کنید تا گزارشِ مبدا با همین بازه باز شود.")
        hint.setObjectName("sectionHint")
        outer.addWidget(hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setSpacing(16)
        scroll.setWidget(self.body)
        outer.addWidget(scroll, stretch=1)

    def _company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh(self) -> None:
        today = datetime.date.today()
        fiscal_year = session.current_fiscal_year
        self.date_from.setDate(fiscal_year.start_date if fiscal_year is not None else today.replace(month=1, day=1))
        self.date_to.setDate(today)
        self.reload()

    def reload(self) -> None:
        raise NotImplementedError

    def open_report(self, report_code: str, options: dict | None = None) -> None:
        if self._main_window is None:
            return
        date_from, date_to = self.date_from.date(), self.date_to.date()
        self._main_window.open_screen(
            f"PURCH_RPT_{report_code}", then=lambda screen: screen.apply_preset(date_from, date_to, options or {}))


class ProcurementExecutiveDashboard(_ProcurementDashboardBase):
    TITLE = "داشبوردِ مدیریتیِ خرید"

    def __init__(self, main_window=None) -> None:
        super().__init__(main_window)
        self.cards: dict[str, KpiCard] = {}
        self._kpis: dict[str, dashboard_service.Kpi] = {}
        grid = QGridLayout()
        grid.setSpacing(16)
        for i, (code, (icon, color)) in enumerate(_KPI_ICONS.items()):
            card = _ClickableKpiCard("", icon, getattr(theme, color), lambda c=code: self._open_kpi(c))
            self.cards[code] = card
            grid.addWidget(card, i // 4, i % 4)
        for col in range(4):
            grid.setColumnStretch(col, 1)
        self.body_layout.addLayout(grid)

        charts = QGridLayout()
        charts.setSpacing(16)
        self.chart_views = {}
        for i, (key, title) in enumerate((
            ("monthly", "روندِ ماهانهٔ خالصِ خرید"), ("suppliers", "۱۰ تامین‌کنندهٔ برتر"),
            ("items", "۱۰ کالایِ پرخرید"), ("categories", "سهمِ گروه‌هایِ کالا"), ("aging", "سنی‌کردنِ بدهی"),
        )):
            card, view = build_chart_card(title)
            self.chart_views[key] = view
            charts.addWidget(card, i // 2, i % 2)
        self.body_layout.addLayout(charts)

    def _open_kpi(self, code: str) -> None:
        kpi = self._kpis.get(code)
        if kpi is not None:
            self.open_report(kpi.report_code, kpi.options)

    def reload(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._decimal_places = companies_service.get_base_currency_decimal_places(company_id)
        date_from, date_to = self.date_from.date(), self.date_to.date()
        self._kpis = {k.code: k for k in dashboard_service.executive_kpis(company_id, date_from, date_to)}
        for code, kpi in self._kpis.items():
            card = self.cards[code]
            card._title_label.setText(kpi.title)
            card.set_value(format_kpi(kpi.value, kpi.kind, self._decimal_places))
            card.setToolTip(f"فرمول: {kpi.formula}\nکلیک: گزارشِ مبدا")
        charts = dashboard_service.executive_charts(company_id, date_from, date_to)
        persian = numerals.to_persian_digits
        render_bar_chart(self.chart_views["monthly"], [persian(str(k)) for k, _v in charts["monthly"]],
                         [v for _k, v in charts["monthly"]], "خالصِ خرید")
        for key in ("suppliers", "items"):
            render_bar_chart(self.chart_views[key], [persian(k.split(" — ")[-1]) for k, _v in charts[key]],
                             [v for _k, v in charts[key]], "خالصِ خرید")
        render_donut_chart(self.chart_views["categories"], [(persian(k), v) for k, v in charts["categories"] if v > 0])
        render_bar_chart(self.chart_views["aging"], [k for k, _v in charts["aging"]], [v for _k, v in charts["aging"]], "مانده")


class ProcurementExceptionDashboard(_ProcurementDashboardBase):
    TITLE = "داشبوردِ استثناهایِ خرید"

    def __init__(self, main_window=None) -> None:
        super().__init__(main_window)
        self._rows: list[dashboard_service.ExceptionRow] = []
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["شدت", "استثنا", "تعداد", "مبلغ", "توضیح", "گزارش"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setMinimumHeight(460)
        self.table.cellDoubleClicked.connect(lambda row, _c: self.open_exception(row))
        self.body_layout.addWidget(self.table)
        card, self.chart_view = build_chart_card("تعدادِ استثناها")
        self.body_layout.addWidget(card)

    def reload(self) -> None:
        company_id = self._company_id()
        if company_id is None:
            return
        self._decimal_places = companies_service.get_base_currency_decimal_places(company_id)
        rows = dashboard_service.exceptions(company_id, self.date_from.date(), self.date_to.date())
        order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        self._rows = sorted(rows, key=lambda r: (r.count == 0, order[r.severity], -r.count))
        self.table.setRowCount(len(self._rows))
        for i, r in enumerate(self._rows):
            cells = [
                dashboard_service.SEVERITY_LABELS[r.severity], r.title, numerals.to_persian_digits(str(r.count)),
                format_kpi(r.amount, "MONEY", self._decimal_places) if r.amount is not None else "",
                r.hint, "باز کردن ←",
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 0 and r.count:
                    item.setForeground(_qcolor(_SEVERITY_COLOR[r.severity]))
                if r.count == 0:
                    item.setForeground(_qcolor("TEXT_SECONDARY"))
                self.table.setItem(i, c, item)
        active = [r for r in self._rows if r.count]
        render_bar_chart(self.chart_view, [r.title for r in active], [r.count for r in active], "تعداد")

    def open_exception(self, row: int) -> None:
        if 0 <= row < len(self._rows):
            r = self._rows[row]
            self.open_report(r.report_code, r.options)


def _qcolor(name: str):
    from PySide6.QtGui import QColor

    return QColor(getattr(theme, name))
