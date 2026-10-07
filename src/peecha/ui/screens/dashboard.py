"""داشبورد — معادلِ Qt برایِ dashboard.py/dashboard.kv در Kivy.

طبقِ درخواستِ صریح («برایِ هر ماژول داشبوردِ مخصوصِ خودش در فرمِ داشبورد
تبِ جدا»): داشبوردِ قدیمی (یک صفحه‌یِ تک) به یک QTabWidget تبدیل شد --
تبِ «کلی» همان خلاصه‌یِ سراسری (شرکت‌ها/کاربران + بنرِ هشدارِ تسویه) را
نگه می‌دارد، و هر ماژول (حسابداری/خزانه‌داری/انبار/فروش/خرید/منابعِ‌
انسانی) تبِ اختصاصیِ خودش را با KPIها/نمودارهایِ واقعیِ همان ماژول دارد.
طبقِ همان اصلِ سرویسِ dashboard.py («همه واقعی رویِ دیتابیس، بدونِ
داده‌یِ ساختگی»)، هیچ‌کدام از این تب‌ها داده‌یِ نمونه ندارند.

برایِ کارایی، هر تب فقط وقتی که فعال می‌شود (یا کلِ داشبورد تازه باز
می‌شود) رفرش می‌شود -- نه هر شش/هفت تب هربار که کاربر فقط می‌خواهد
داشبورد را ببیند."""

from __future__ import annotations

import datetime
import decimal

from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QPieSeries, QValueAxis
from PySide6.QtCore import Qt, QMargins
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from peecha import numerals, session
from peecha.ui import theme
from peecha.ui.widgets import KpiCard
from peecha.services import commercial_settlements as settlements_service
from peecha.services import dashboard as dashboard_service


class _KpiCard(KpiCard):
    def set_value(self, value: int) -> None:
        super().set_value(_to_persian_digits(str(value)))


_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"


def _to_persian_digits(text: str) -> str:
    return "".join(_PERSIAN_DIGITS[int(ch)] if ch.isdigit() else ch for ch in text)


def _company_id() -> int | None:
    return session.current_company.company_id if session.current_company else None


# ---------------------------------------------------------------------
# کارت/نمودارِ مشترک -- طبقِ بازطراحیِ «تبِ جدا برایِ هر ماژول»، این‌ها
# دیگر متدِ خودِ DashboardScreen نیستند تا هر تب هم بتواند مستقلاً از
# آن‌ها استفاده کند.
# ---------------------------------------------------------------------
def build_chart_card(title_text: str) -> tuple[QWidget, QChartView]:
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


def _themed_chart() -> QChart:
    chart = QChart()
    chart.legend().setVisible(False)
    chart.setBackgroundVisible(False)
    return chart


def _style_axis(axis) -> None:
    axis.setLabelsColor(QColor(theme.TEXT_SECONDARY))
    axis.setLinePen(QPen(QColor(theme.DIVIDER)))
    axis.setGridLineColor(QColor(theme.DIVIDER))
    label_font = QFont()
    label_font.setPointSize(9)
    axis.setLabelsFont(label_font)


def render_bar_chart(
    chart_view: QChartView, labels: list[str], values: list[int | decimal.Decimal], series_name: str = "مقدار",
) -> None:
    chart = _themed_chart()

    bar_set = QBarSet(series_name)
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
    _style_axis(axis_x)
    axis_x.setGridLineVisible(False)

    axis_y = QValueAxis()
    max_value = max((float(v) for v in values), default=1)
    axis_y.setRange(0, max(max_value, 1))
    chart.addAxis(axis_y, Qt.AlignLeft)
    series.attachAxis(axis_y)
    _style_axis(axis_y)

    chart_view.setChart(chart)


def render_donut_chart(chart_view: QChartView, breakdown: list[tuple[str, int | decimal.Decimal]]) -> None:
    chart = _themed_chart()
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
    chart_view.setChart(chart)


def render_grouped_bar_chart(chart_view: QChartView, labels: list[str], series_values: dict[str, list]) -> None:
    chart = _themed_chart()
    chart.legend().setVisible(True)
    chart.legend().setAlignment(Qt.AlignBottom)
    chart.legend().setLabelColor(QColor(theme.TEXT_SECONDARY))
    series = QBarSeries()
    series.setBarWidth(0.7)
    colors = [theme.ACCENT, theme.CHART_TEAL, theme.CHART_PURPLE, theme.WARNING]
    max_value = 1.0
    for i, (name, values) in enumerate(series_values.items()):
        bar_set = QBarSet(name)
        bar_set.append([float(v) for v in values])
        bar_set.setColor(QColor(colors[i % len(colors)]))
        series.append(bar_set)
        max_value = max([max_value] + [float(v) for v in values])
    chart.addSeries(series)
    axis_x = QBarCategoryAxis()
    axis_x.append(labels)
    chart.addAxis(axis_x, Qt.AlignBottom)
    series.attachAxis(axis_x)
    _style_axis(axis_x)
    axis_x.setGridLineVisible(False)
    axis_y = QValueAxis()
    axis_y.setRange(0, max_value)
    chart.addAxis(axis_y, Qt.AlignLeft)
    series.attachAxis(axis_y)
    _style_axis(axis_y)
    chart_view.setChart(chart)


def _kpi_grid(layout: QVBoxLayout, cards: list[QWidget], columns: int = 4) -> None:
    grid = QGridLayout()
    grid.setSpacing(16)
    for i, card in enumerate(cards):
        grid.addWidget(card, i // columns, i % columns)
    for col in range(columns):
        grid.setColumnStretch(col, 1)
    layout.addLayout(grid)


def _module_links(layout: QVBoxLayout, main_window, links: list[tuple[str, str]]) -> list[QPushButton]:
    """R276: پیوند به داشبوردهایِ تخصصیِ هر ماژول (که در منویِ همان ماژول پراکنده بودند)."""
    row = QHBoxLayout()
    row.setSpacing(8)
    buttons = []
    for label, nav_code in links:
        button = QPushButton(label)
        button.setCursor(Qt.PointingHandCursor)
        button.setProperty("nav_code", nav_code)
        button.clicked.connect(
            lambda _checked=False, code=nav_code: main_window.open_screen(code) if main_window is not None else None
        )
        row.addWidget(button)
        buttons.append(button)
    row.addStretch(1)
    layout.addLayout(row)
    return buttons


def _scrollable(tab: QWidget) -> QVBoxLayout:
    """محتوایِ تب داخلِ اسکرول، تا کارت‌ها و نمودارها در پنجرهٔ کوچک له نشوند."""
    holder = QVBoxLayout(tab)
    holder.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    body = QWidget()
    scroll.setWidget(body)
    holder.addWidget(scroll)
    outer = QVBoxLayout(body)
    outer.setContentsMargins(24, 24, 24, 24)
    outer.setSpacing(20)
    return outer


MODULE_DASHBOARD_LINKS = [
    ("داشبوردِ مدیریتیِ خرید", "PURCH_RPT_DASH_EXEC"),
    ("استثناهایِ خرید", "PURCH_RPT_DASH_EXCEPTIONS"),
    ("داشبوردِ انبار", "INV_RPT_DASHBOARD"),
    ("داشبوردِ بهایِ تمام‌شده", "COST_DASHBOARD"),
    ("داشبوردِ تولید", "PRD_DASHBOARD"),
    ("داشبوردِ دارایی‌ها", "FA_DASHBOARD"),
    ("دستیارِ فروش", "SALES_ASSISTANT"),
]


def _kpi_row(layout: QVBoxLayout, cards: list[QWidget]) -> None:
    cards_layout = QGridLayout()
    cards_layout.setSpacing(16)
    for i, card in enumerate(cards):
        cards_layout.addWidget(card, 0, i)
        cards_layout.setColumnStretch(i, 1)
    layout.addLayout(cards_layout)


class _OverviewTab(QWidget):
    """تبِ «کلی» -- خلاصه‌یِ سراسری (نه مخصوصِ یک ماژول): شمارشِ
    شرکت‌ها/کاربران (که به هیچ ماژولِ خاصی تعلق ندارند) و بنرِ هشدارِ
    موعدِ تسویه (چون اولین صفحه‌ای‌ست که کاربر می‌بیند)."""

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self._due_sales_count = 0
        self._due_purchase_count = 0

        outer = _scrollable(self)

        subtitle = QLabel("خلاصه‌یِ سراسریِ سیستم")
        subtitle.setObjectName("sectionHint")
        outer.addWidget(subtitle)

        # طبقِ درخواستِ صریح («آلارم در فرمِ اصلیِ برنامه نمایش بده تا
        # کاربر مطلع بشه»): بنرِ هشدارِ موعدِ تسویه همین‌جا می‌ماند --
        # همان اولین تبی‌ست که کاربر با آن روبه‌رو می‌شود.
        self.alarm_banner = QPushButton("")
        self.alarm_banner.setCursor(Qt.PointingHandCursor)
        self.alarm_banner.setVisible(False)
        self.alarm_banner.clicked.connect(self._open_due_settlements)
        outer.addWidget(self.alarm_banner)

        # طبقِ ادامهٔ فهرستِ درخواستی («هشدارهایِ هوشمندِ فراگیر»): بنرِ
        # بالا فقط موعدِ تسویه را پوشش می‌دهد -- این کانتینرِ جداگانه،
        # هشدارهایِ ازپیش‌ساخته‌شدهٔ ماژول‌هایِ دیگر (اقساطِ معوقه،
        # اقداماتِ فوریِ دستیارِ فروش) را کنارِ هم نشان می‌دهد.
        self._smart_alerts_layout = QVBoxLayout()
        self._smart_alerts_layout.setSpacing(8)
        outer.addLayout(self._smart_alerts_layout)
        self._smart_alert_buttons: list[QPushButton] = []

        # R276: نمایِ مدیریتیِ همهٔ ماژول‌ها (قبلاً فقط شرکت‌ها/کاربران).
        self._exec_cards = {
            "sales_this_month": KpiCard("فروشِ این ماه", "🧾", theme.ACCENT),
            "purchases_this_month": KpiCard("خریدِ این ماه", "🛒", theme.CHART_PURPLE),
            "receivables": KpiCard("مطالباتِ تسویه‌نشده", "📥", theme.WARNING),
            "payables": KpiCard("بدهیِ تسویه‌نشده", "📤", theme.DANGER),
            "inventory_value": KpiCard("ارزشِ موجودیِ انبار", "📦", theme.CHART_TEAL),
            "received_checks_amount": KpiCard("چک‌هایِ دریافتیِ درجریان", "🏦", theme.ACCENT),
            "open_production_orders": _KpiCard("دستورهایِ تولیدِ باز", "🏭", theme.CHART_PURPLE),
            "fixed_assets_book_value": KpiCard("ارزشِ دفتریِ دارایی‌ها", "🏗️", theme.CHART_TEAL),
        }
        _kpi_grid(outer, list(self._exec_cards.values()))

        charts_layout = QGridLayout()
        charts_layout.setSpacing(16)
        charts_layout.setColumnStretch(0, 3)
        charts_layout.setColumnStretch(1, 2)
        trend_card, self.trend_chart_view = build_chart_card("فروش و خرید در ۶ ماهِ اخیر")
        charts_layout.addWidget(trend_card, 0, 0)
        stock_card, self.stock_chart_view = build_chart_card("ارزشِ موجودی به تفکیکِ انبار")
        charts_layout.addWidget(stock_card, 0, 1)
        outer.addLayout(charts_layout)

        links_title = QLabel("داشبوردهایِ تخصصیِ ماژول‌ها")
        links_title.setObjectName("cardTitle")
        outer.addWidget(links_title)
        self.module_link_buttons = _module_links(outer, main_window, MODULE_DASHBOARD_LINKS)

        self.card_companies = _KpiCard("شرکت‌ها", "🏢", theme.ACCENT)
        self.card_users = _KpiCard("کاربران", "👥", theme.CHART_TEAL)
        _kpi_row(outer, [self.card_companies, self.card_users])
        outer.addStretch(1)

    def refresh(self) -> None:
        company_id = _company_id()
        self.card_companies.refresh_theme(theme.ACCENT)
        self.card_users.refresh_theme(theme.CHART_TEAL)
        self.card_companies.set_value(dashboard_service.count_companies())
        self.card_users.set_value(dashboard_service.count_users())
        overview = dashboard_service.executive_overview(company_id)
        for key, card in self._exec_cards.items():
            value = getattr(overview, key)
            card.set_value(value if isinstance(value, int) else numerals.format_company_amount(value))
        labels, series = dashboard_service.sales_vs_purchases_per_month(company_id)
        render_grouped_bar_chart(self.trend_chart_view, labels, series)
        render_donut_chart(self.stock_chart_view, dashboard_service.inventory_value_by_warehouse(company_id))
        self._refresh_alarm_banner(company_id)
        self._refresh_smart_alerts(company_id)

    def _refresh_smart_alerts(self, company_id: int | None) -> None:
        while self._smart_alerts_layout.count():
            item = self._smart_alerts_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._smart_alert_buttons = []

        severity_colors = {"danger": theme.DANGER, "warning": theme.WARNING}
        for alert in dashboard_service.list_smart_alerts(company_id):
            button = QPushButton(f"🔔 {alert.title} — برایِ مشاهده کلیک کنید.")
            button.setCursor(Qt.PointingHandCursor)
            color = severity_colors.get(alert.severity, theme.WARNING)
            button.setStyleSheet(
                f"background-color: {color}; color: white; font-weight: bold; padding: 10px 14px; "
                "border-radius: 8px; text-align: right; border: none;"
            )
            button.clicked.connect(lambda _checked=False, code=alert.nav_code: self._open_nav_code(code))
            self._smart_alerts_layout.addWidget(button)
            self._smart_alert_buttons.append(button)

    def _open_nav_code(self, nav_code: str) -> None:
        if self._main_window is not None:
            self._main_window.open_screen(nav_code)

    def _refresh_alarm_banner(self, company_id: int | None) -> None:
        self._due_sales_count = 0
        self._due_purchase_count = 0
        if company_id is None:
            self.alarm_banner.setVisible(False)
            return
        alarm_settings = settlements_service.get_alarm_settings(company_id)
        if not alarm_settings.is_enabled:
            self.alarm_banner.setVisible(False)
            return
        self._due_sales_count = len(settlements_service.list_invoices_due_soon(company_id, "SALES_INVOICE"))
        self._due_purchase_count = len(settlements_service.list_invoices_due_soon(company_id, "PURCHASE_INVOICE"))
        total = self._due_sales_count + self._due_purchase_count
        if total == 0:
            self.alarm_banner.setVisible(False)
            return
        self.alarm_banner.setText(
            f"⏰ {_to_persian_digits(str(total))} فاکتور تا {_to_persian_digits(str(alarm_settings.alarm_days_before))} "
            f"روزِ دیگر (یا پیش‌ازاین) به موعدِ تسویه می‌رسند — {_to_persian_digits(str(self._due_sales_count))} فروش، "
            f"{_to_persian_digits(str(self._due_purchase_count))} خرید. برایِ مشاهده کلیک کنید."
        )
        self.alarm_banner.setStyleSheet(
            f"background-color: {theme.WARNING}; color: white; font-weight: bold; padding: 10px 14px; "
            "border-radius: 8px; text-align: right; border: none;"
        )
        self.alarm_banner.setVisible(True)

    def _open_due_settlements(self) -> None:
        if self._main_window is None:
            return
        nav_code = "TREASURY_SETTLEMENT_SALES" if self._due_sales_count > 0 else "TREASURY_SETTLEMENT_PURCHASE"
        self._main_window.open_screen(nav_code)


class _ModuleTab(QWidget):
    """پایهٔ تب‌هایِ ماژول: اسکرول + ردیفِ پیوند به داشبوردِ کاملِ همان ماژول."""

    LINKS: list[tuple[str, str]] = []

    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window
        self.outer = _scrollable(self)
        self.link_buttons = _module_links(self.outer, main_window, self.LINKS) if self.LINKS else []


def _format_kpi(kpi) -> str:
    if kpi.value is None:
        return "—"
    if kpi.kind == "MONEY":
        return numerals.format_company_amount(kpi.value)
    if kpi.kind == "PERCENT":
        return _to_persian_digits(f"{kpi.value}٪")
    return _to_persian_digits(str(kpi.value))


class _ServiceDashboardTab(_ModuleTab):
    """R276: خلاصهٔ داشبوردِ تخصصیِ ماژول (تولید/دارایی) از همان سرویسِ خودش، در یک تب."""

    KPI_CODES: tuple[str, ...] = ()
    CHARTS: tuple[tuple[str, str], ...] = ()

    def __init__(self, main_window=None) -> None:
        super().__init__(main_window)
        colors = [theme.ACCENT, theme.CHART_TEAL, theme.CHART_PURPLE, theme.WARNING]
        self.kpi_cards = {code: KpiCard(title, "📊", colors[i % len(colors)])
                          for i, (code, title) in enumerate(self.KPI_CODES)}
        _kpi_grid(self.outer, list(self.kpi_cards.values()))
        charts_layout = QGridLayout()
        charts_layout.setSpacing(16)
        self.chart_views = {}
        for i, (key, title) in enumerate(self.CHARTS):
            card, view = build_chart_card(title)
            charts_layout.addWidget(card, 0, i)
            charts_layout.setColumnStretch(i, 1)
            self.chart_views[key] = view
        self.outer.addLayout(charts_layout)
        self.alerts_label = QLabel("")
        self.alerts_label.setObjectName("sectionHint")
        self.alerts_label.setWordWrap(True)
        self.outer.addWidget(self.alerts_label)
        self.outer.addStretch(1)

    def _load(self, company_id: int):
        raise NotImplementedError

    def refresh(self) -> None:
        company_id = _company_id()
        if company_id is None:
            return
        today = datetime.date.today()
        kpis, charts, alert_rows, _alerts = self._load(company_id, today - datetime.timedelta(days=365), today)
        by_code = {k.code: k for k in kpis}
        for code, card in self.kpi_cards.items():
            card.set_value(_format_kpi(by_code[code]) if code in by_code else "—")
        for key, view in self.chart_views.items():
            chart = charts.get(key) or {"kind": "bar", "labels": [], "series": {}}
            values = next(iter(chart["series"].values()), [])
            if chart["kind"] == "donut":
                render_donut_chart(view, list(zip(chart["labels"], values)))
            else:
                render_bar_chart(view, [str(x) for x in chart["labels"]], values, next(iter(chart["series"]), "مقدار"))
        self.alerts_label.setText(
            "هشدارها: " + "، ".join(f"{label} ({_to_persian_digits(str(n))})" for label, n in alert_rows)
            if alert_rows else "هشدارِ فعالی وجود ندارد."
        )


class _ProductionTab(_ServiceDashboardTab):
    LINKS = [("داشبوردِ کاملِ تولید", "PRD_DASHBOARD")]
    KPI_CODES = (("ORDERS", "دستورهایِ تولید"), ("IN_PROGRESS", "در حالِ تولید"), ("DELAYED", "عقب‌افتاده"),
                 ("SHORTAGE", "کمبودِ مواد"), ("VALUE", "ارزشِ تولید"), ("ACTUAL", "بهایِ واقعی"),
                 ("VARIANCE", "انحرافِ بها"), ("SCRAP", "ضایعات"))
    CHARTS = (("by_period", "تولید به تفکیکِ دوره"), ("elements", "عناصرِ بهایِ تمام‌شده"))

    def _load(self, company_id, date_from, date_to):
        from peecha.services.production import dashboard as prd_dashboard

        return prd_dashboard.dashboard(company_id, date_from, date_to)


class _FixedAssetsTab(_ServiceDashboardTab):
    LINKS = [("داشبوردِ کاملِ دارایی‌ها", "FA_DASHBOARD")]
    KPI_CODES = (("COUNT", "تعدادِ دارایی‌ها"), ("GROSS", "بهایِ تمام‌شده"), ("ACCUM", "استهلاکِ انباشته"),
                 ("NBV", "ارزشِ دفتری"), ("IN_SERVICE", "در بهره‌برداری"), ("MAINTENANCE", "در تعمیر"),
                 ("FULLY_DEPRECIATED", "کاملاً مستهلک"), ("DISPOSED", "واگذارشده"))
    CHARTS = (("by_category", "ارزشِ دفتری به تفکیکِ طبقه"), ("status", "وضعیتِ دارایی‌ها"))

    def _load(self, company_id, date_from, date_to):
        from peecha.services.fixed_assets import dashboard as fa_dashboard

        return fa_dashboard.dashboard(company_id, date_from, date_to)


class _AccountingTab(QWidget):
    """تبِ «حسابداری»: حساب‌هایِ کدینگ، اسنادِ حسابداری، سالِ مالیِ باز،
    و همان دو نموداری که پیش‌تر در تبِ کلی بودند (چون کاملاً حسابداری‌اند،
    نه سراسری)."""

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(20)

        self.card_accounts = _KpiCard("حساب‌هایِ کدینگ", "📚", theme.CHART_PURPLE)
        self.card_entries = _KpiCard("اسنادِ حسابداری", "🧾", theme.WARNING)
        self.card_open_years = _KpiCard("سالِ مالیِ باز", "📅", theme.CHART_TEAL)
        _kpi_row(outer, [self.card_accounts, self.card_entries, self.card_open_years])

        charts_layout = QGridLayout()
        charts_layout.setSpacing(16)
        charts_layout.setColumnStretch(0, 1)
        charts_layout.setColumnStretch(1, 1)
        entries_card, self.entries_chart_view = build_chart_card("تعدادِ اسناد در ۶ ماهِ اخیر")
        charts_layout.addWidget(entries_card, 0, 0)
        status_card, self.status_chart_view = build_chart_card("وضعیتِ اسنادِ حسابداری")
        charts_layout.addWidget(status_card, 0, 1)
        outer.addLayout(charts_layout, stretch=1)

    def refresh(self) -> None:
        company_id = _company_id()
        self.card_accounts.refresh_theme(theme.CHART_PURPLE)
        self.card_entries.refresh_theme(theme.WARNING)
        self.card_open_years.refresh_theme(theme.CHART_TEAL)

        self.card_accounts.set_value(dashboard_service.count_chart_of_accounts(company_id))
        self.card_entries.set_value(dashboard_service.count_journal_entries(company_id))
        self.card_open_years.set_value(dashboard_service.open_fiscal_years_count(company_id))

        labels, values = dashboard_service.journal_entries_per_month(company_id)
        render_bar_chart(self.entries_chart_view, labels, values, "تعدادِ اسناد")

        by_status = dashboard_service.journal_entries_by_status(company_id)
        render_donut_chart(self.status_chart_view, by_status)


class _TreasuryTab(QWidget):
    """تبِ «خزانه‌داری»: چک‌هایِ دریافتیِ نزدِ صندوق، چک‌هایِ پرداختیِ
    درجریان، و مبلغ/تعدادِ اقساطِ معوقه."""

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(20)

        self.card_received_checks = _KpiCard("چک‌هایِ دریافتیِ نزدِ صندوق", "📥", theme.CHART_TEAL)
        self.card_issued_checks = _KpiCard("چک‌هایِ پرداختیِ درجریان", "📤", theme.WARNING)
        self.card_overdue_count = _KpiCard("تعدادِ اقساطِ معوقه", "⏰", theme.DANGER)
        self.card_overdue_amount = KpiCard("مبلغِ اقساطِ معوقه", "💸", theme.DANGER)
        _kpi_row(outer, [
            self.card_received_checks, self.card_issued_checks, self.card_overdue_count, self.card_overdue_amount,
        ])

        chart_card, self.checks_chart_view = build_chart_card("مبلغِ چک‌هایِ درجریان (دریافتی/پرداختی)")
        outer.addWidget(chart_card, stretch=1)

    def refresh(self) -> None:
        company_id = _company_id()
        self.card_received_checks.refresh_theme(theme.CHART_TEAL)
        self.card_issued_checks.refresh_theme(theme.WARNING)
        self.card_overdue_count.refresh_theme(theme.DANGER)
        self.card_overdue_amount.refresh_theme(theme.DANGER)

        summary = dashboard_service.treasury_summary(company_id)
        self.card_received_checks.set_value(summary.pending_received_checks_count)
        self.card_issued_checks.set_value(summary.pending_issued_checks_count)
        self.card_overdue_count.set_value(summary.overdue_installments_count)
        self.card_overdue_amount.set_value(numerals.format_company_amount(summary.overdue_installments_amount))

        render_bar_chart(
            self.checks_chart_view, ["دریافتیِ درجریان", "پرداختیِ درجریان"],
            [summary.pending_received_checks_amount, summary.pending_issued_checks_amount], "مبلغ",
        )


class _InventoryTab(QWidget):
    """تبِ «انبار»: ارزشِ کلِ موجودی، تعدادِ کالا/انبارِ فعال، ردیف‌هایِ
    موجودیِ منفی، و ارزشِ موجودی به تفکیکِ انبار."""

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(20)

        self.card_value = KpiCard("ارزشِ کلِ موجودی", "💰", theme.ACCENT)
        self.card_items = _KpiCard("کالایِ فعال", "📦", theme.CHART_TEAL)
        self.card_warehouses = _KpiCard("انبارِ فعال", "🏬", theme.CHART_PURPLE)
        self.card_negative = _KpiCard("ردیف‌هایِ موجودیِ منفی", "⚠️", theme.DANGER)
        _kpi_row(outer, [self.card_value, self.card_items, self.card_warehouses, self.card_negative])

        chart_card, self.value_chart_view = build_chart_card("ارزشِ موجودی به تفکیکِ انبار")
        outer.addWidget(chart_card, stretch=1)

    def refresh(self) -> None:
        company_id = _company_id()
        self.card_value.refresh_theme(theme.ACCENT)
        self.card_items.refresh_theme(theme.CHART_TEAL)
        self.card_warehouses.refresh_theme(theme.CHART_PURPLE)
        self.card_negative.refresh_theme(theme.DANGER)

        summary = dashboard_service.inventory_summary(company_id)
        self.card_value.set_value(numerals.format_company_amount(summary.total_value))
        self.card_items.set_value(summary.active_items_count)
        self.card_warehouses.set_value(summary.warehouses_count)
        self.card_negative.set_value(summary.negative_balance_count)

        by_warehouse = dashboard_service.inventory_value_by_warehouse(company_id)
        render_donut_chart(self.value_chart_view, by_warehouse)


class _CommercialTab(QWidget):
    """تبِ «فروش»/«خرید» -- هردو دقیقاً یک الگو دارند، فقط نوعِ سند
    (SALES_INVOICE/PURCHASE_INVOICE) و برچسب‌ها فرق می‌کند."""

    def __init__(self, document_type_code: str, month_title: str, party_title: str, main_window=None) -> None:
        super().__init__()
        self._document_type_code = document_type_code
        self._main_window = main_window
        self._is_sales = document_type_code == "SALES_INVOICE"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(20)

        self.card_month = KpiCard(month_title, "🧾", theme.ACCENT)
        self.card_unsettled_count = _KpiCard("فاکتورهایِ تسویه‌نشده", "⏳", theme.WARNING)
        self.card_unsettled_amount = KpiCard("مبلغِ تسویه‌نشده", "💳", theme.WARNING)
        _kpi_row(outer, [self.card_month, self.card_unsettled_count, self.card_unsettled_amount])

        if self._is_sales:
            # طبقِ ادامهٔ فهرستِ درخواستی («پیشخوانِ فروش»): به‌جایِ ساختِ
            # یک صفحه‌یِ کاملاً جدا، همین تبِ ازپیش‌موجودِ «فروش» به
            # پیشخوانِ فروش تبدیل می‌شود -- سه محورِ هوشِ فروشِ ازپیش‌
            # ساخته‌شده (پیش‌بینی از R79، اقداماتِ پیشنهادی از R70/R74،
            # سودآورترین مشتری از R78) کنارِ هم قرار می‌گیرند.
            self.card_forecast = KpiCard("پیش‌بینیِ فروشِ ماهِ بعد", "🔮", theme.CHART_PURPLE)
            self.card_actions = _KpiCard("اقداماتِ پیشنهادیِ امروز", "📋", theme.DANGER)
            self.card_top_profit = KpiCard("سودآورترین مشتریِ این ماه", "🏆", theme.CHART_TEAL)
            _kpi_row(outer, [self.card_forecast, self.card_actions, self.card_top_profit])

            self.top_action_banner = QPushButton("")
            self.top_action_banner.setCursor(Qt.PointingHandCursor)
            self.top_action_banner.setVisible(False)
            self.top_action_banner.clicked.connect(self._open_sales_assistant)
            outer.addWidget(self.top_action_banner)

        charts_layout = QGridLayout()
        charts_layout.setSpacing(16)
        charts_layout.setColumnStretch(0, 1)
        charts_layout.setColumnStretch(1, 1)
        trend_card, self.trend_chart_view = build_chart_card("روندِ ۶ ماهِ اخیر")
        charts_layout.addWidget(trend_card, 0, 0)
        top_card, self.top_chart_view = build_chart_card(party_title)
        charts_layout.addWidget(top_card, 0, 1)
        outer.addLayout(charts_layout, stretch=1)

    def refresh(self) -> None:
        company_id = _company_id()
        self.card_month.refresh_theme(theme.ACCENT)
        self.card_unsettled_count.refresh_theme(theme.WARNING)
        self.card_unsettled_amount.refresh_theme(theme.WARNING)

        summary = dashboard_service.commercial_summary(company_id, self._document_type_code)
        self.card_month.set_value(numerals.format_company_amount(summary.this_month_total))
        self.card_unsettled_count.set_value(summary.unsettled_count)
        self.card_unsettled_amount.set_value(numerals.format_company_amount(summary.unsettled_amount))

        labels, values = dashboard_service.commercial_amount_per_month(company_id, self._document_type_code)
        render_bar_chart(self.trend_chart_view, labels, values, "مبلغ")

        top = dashboard_service.top_counterparties(company_id, self._document_type_code)
        render_donut_chart(self.top_chart_view, top)

        if self._is_sales:
            self.card_forecast.refresh_theme(theme.CHART_PURPLE)
            self.card_actions.refresh_theme(theme.DANGER)
            self.card_top_profit.refresh_theme(theme.CHART_TEAL)
            center = dashboard_service.sales_command_center(company_id)
            self.card_forecast.set_value(
                numerals.format_company_amount(center.forecast_next_month)
                if center.forecast_next_month is not None else "—"
            )
            self.card_actions.set_value(center.action_items_count)
            if center.top_profit_customer_name is not None:
                self.card_top_profit.set_value(
                    f"{center.top_profit_customer_name} "
                    f"({numerals.format_company_amount(center.top_profit_customer_amount)})"
                )
            else:
                self.card_top_profit.set_value("—")
            self._refresh_top_action_banner(center)

    def _refresh_top_action_banner(self, center) -> None:
        if center.top_action_title is None:
            self.top_action_banner.setVisible(False)
            return
        severity_colors = {"danger": theme.DANGER, "warning": theme.WARNING, "success": theme.CHART_TEAL}
        color = severity_colors.get(center.top_action_severity, theme.WARNING)
        self.top_action_banner.setText(
            f"🧠 مهم‌ترین اقدامِ پیشنهادیِ امروز: {center.top_action_title} — برایِ مشاهده‌یِ کامل کلیک کنید."
        )
        self.top_action_banner.setStyleSheet(
            f"background-color: {color}; color: white; font-weight: bold; padding: 10px 14px; "
            "border-radius: 8px; text-align: right; border: none;"
        )
        self.top_action_banner.setVisible(True)

    def _open_sales_assistant(self) -> None:
        if self._main_window is not None:
            self._main_window.open_screen("SALES_ASSISTANT")


class _HrTab(QWidget):
    """تبِ «منابعِ‌انسانی» -- طبقِ همان اصلِ «فقط چیزهایی که واقعاً
    قابلِ‌محاسبه‌اند» (این ماژول هنوز جوان‌تر از بقیه است)، فقط شمارشِ
    کارکنان، بدونِ نمودارِ اضافی."""

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(20)

        self.card_total = _KpiCard("کلِ کارکنان", "👤", theme.ACCENT)
        self.card_active = _KpiCard("کارکنانِ فعال", "✅", theme.CHART_TEAL)
        _kpi_row(outer, [self.card_total, self.card_active])
        units_card, self.units_chart_view = build_chart_card("کارکنانِ فعال به تفکیکِ واحدِ سازمانی")
        outer.addWidget(units_card, stretch=1)

    def refresh(self) -> None:
        company_id = _company_id()
        self.card_total.refresh_theme(theme.ACCENT)
        self.card_active.refresh_theme(theme.CHART_TEAL)
        summary = dashboard_service.hr_summary(company_id)
        self.card_total.set_value(summary.total_employees)
        self.card_active.set_value(summary.active_employees)
        render_donut_chart(self.units_chart_view, dashboard_service.employees_by_org_unit(company_id))


class DashboardScreen(QWidget):
    def __init__(self, main_window=None) -> None:
        super().__init__()
        self._main_window = main_window

        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 32, 20, 20)
        outer.setSpacing(16)

        title = QLabel("داشبورد")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, stretch=1)

        self._overview_tab = _OverviewTab(main_window)
        self.tabs.addTab(self._overview_tab, "کلی")
        self._accounting_tab = _AccountingTab()
        self._add_module_tab(self._accounting_tab, "حسابداری", [
            ("اسنادِ حسابداری", "GL_JE_LIST"), ("تفصیلی‌ها", "GL_TAFSILI"), ("کدینگ", "GL_COA")])
        self._treasury_tab = _TreasuryTab()
        self._add_module_tab(self._treasury_tab, "خزانه‌داری", [
            ("چک‌هایِ درجریان", "TREASURY_CHECKS_DUE"), ("اقساط", "TREASURY_INSTALLMENTS"),
            ("تسویهٔ فاکتورهایِ فروش", "TREASURY_SETTLEMENT_SALES")])
        self._inventory_tab = _InventoryTab()
        self._add_module_tab(self._inventory_tab, "انبار", [
            ("داشبوردِ کاملِ انبار", "INV_RPT_DASHBOARD"), ("داشبوردِ بهایِ تمام‌شده", "COST_DASHBOARD")])
        self._sales_tab = _CommercialTab("SALES_INVOICE", "فروشِ این ماه", "پُرفروش‌ترین مشتریان", main_window)
        self._add_module_tab(self._sales_tab, "فروش", [
            ("دستیارِ فروش", "SALES_ASSISTANT"), ("اسنادِ فروش", "SALES_DOCUMENTS_LIST")])
        self._purchase_tab = _CommercialTab("PURCHASE_INVOICE", "خریدِ این ماه", "پُرخریدترین تامین‌کنندگان")
        self._add_module_tab(self._purchase_tab, "خرید", [
            ("داشبوردِ مدیریتیِ خرید", "PURCH_RPT_DASH_EXEC"), ("استثناهایِ خرید", "PURCH_RPT_DASH_EXCEPTIONS")])
        self._production_tab = _ProductionTab(main_window)
        self.tabs.addTab(self._production_tab, "تولید")
        self._fixed_assets_tab = _FixedAssetsTab(main_window)
        self.tabs.addTab(self._fixed_assets_tab, "دارایی‌هایِ ثابت")
        self._hr_tab = _HrTab()
        self._add_module_tab(self._hr_tab, "منابعِ‌انسانی", [
            ("واحدهایِ سازمانی", "HR_ORG_UNITS"), ("محاسبهٔ حقوق", "HR_PAYROLL_RUN"),
            ("خلاصهٔ کارکرد", "HR_ATTENDANCE_SUMMARY")])

        self._tabs_in_order = [
            self._overview_tab, self._accounting_tab, self._treasury_tab, self._inventory_tab,
            self._sales_tab, self._purchase_tab, self._production_tab, self._fixed_assets_tab, self._hr_tab,
        ]
        # طبقِ باگِ کشف‌شده: اگر این اتصال قبل از addTabهایِ بالا وصل
        # می‌شد، همان اولین addTab (که خودش currentChanged(0) را امیت
        # می‌کند) پیش از ساختِ self._tabs_in_order اجرا می‌شد و
        # AttributeError می‌داد -- برایِ همین اتصال باید *بعدِ* این لیست
        # وصل شود.
        self.tabs.currentChanged.connect(self._refresh_tab)

        # طبقِ سازگاریِ عقب‌رو: بنرِ هشدارِ موعدِ تسویه پیش از این
        # مستقیماً رویِ خودِ DashboardScreen بود -- حالا در تبِ «کلی»
        # است، ولی این ارجاع برایِ هر کدِ بیرونی (یا تستی) که هنوز
        # dashboard_screen.alarm_banner را می‌خواهد نگه داشته می‌شود.
        self.alarm_banner = self._overview_tab.alarm_banner

    def _add_module_tab(self, tab: QWidget, title: str, links: list[tuple[str, str]]) -> None:
        """R276: هر تبِ ماژول پیوندِ مستقیم به داشبورد/فرم‌هایِ تخصصیِ همان ماژول دارد."""
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(24, 12, 24, 0)
        layout.setSpacing(0)
        tab.link_buttons = _module_links(layout, self._main_window, links)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(tab)
        layout.addWidget(scroll, stretch=1)
        self.tabs.addTab(wrapper, title)

    def refresh(self) -> None:
        """طبقِ بازطراحیِ تب‌به‌تب: فقط تبِ فعلاً فعال رفرش می‌شود -- نه
        هر هفت تب هربار که کاربر داشبورد را باز می‌کند (کارایی)."""
        self._refresh_tab(self.tabs.currentIndex())

    def _refresh_tab(self, index: int) -> None:
        if 0 <= index < len(self._tabs_in_order):
            self._tabs_in_order[index].refresh()
