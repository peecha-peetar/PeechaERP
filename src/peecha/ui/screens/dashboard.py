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

import decimal

from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QPieSeries, QValueAxis
from PySide6.QtCore import Qt, QMargins
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget

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
def _build_chart_card(title_text: str) -> tuple[QWidget, QChartView]:
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


def _render_bar_chart(
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


def _render_donut_chart(chart_view: QChartView, breakdown: list[tuple[str, int | decimal.Decimal]]) -> None:
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

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(20)

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
        self._refresh_alarm_banner(company_id)

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
        entries_card, self.entries_chart_view = _build_chart_card("تعدادِ اسناد در ۶ ماهِ اخیر")
        charts_layout.addWidget(entries_card, 0, 0)
        status_card, self.status_chart_view = _build_chart_card("وضعیتِ اسنادِ حسابداری")
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
        _render_bar_chart(self.entries_chart_view, labels, values, "تعدادِ اسناد")

        by_status = dashboard_service.journal_entries_by_status(company_id)
        _render_donut_chart(self.status_chart_view, by_status)


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

        chart_card, self.checks_chart_view = _build_chart_card("مبلغِ چک‌هایِ درجریان (دریافتی/پرداختی)")
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

        _render_bar_chart(
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

        chart_card, self.value_chart_view = _build_chart_card("ارزشِ موجودی به تفکیکِ انبار")
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
        _render_donut_chart(self.value_chart_view, by_warehouse)


class _CommercialTab(QWidget):
    """تبِ «فروش»/«خرید» -- هردو دقیقاً یک الگو دارند، فقط نوعِ سند
    (SALES_INVOICE/PURCHASE_INVOICE) و برچسب‌ها فرق می‌کند."""

    def __init__(self, document_type_code: str, month_title: str, party_title: str) -> None:
        super().__init__()
        self._document_type_code = document_type_code

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(20)

        self.card_month = KpiCard(month_title, "🧾", theme.ACCENT)
        self.card_unsettled_count = _KpiCard("فاکتورهایِ تسویه‌نشده", "⏳", theme.WARNING)
        self.card_unsettled_amount = KpiCard("مبلغِ تسویه‌نشده", "💳", theme.WARNING)
        _kpi_row(outer, [self.card_month, self.card_unsettled_count, self.card_unsettled_amount])

        charts_layout = QGridLayout()
        charts_layout.setSpacing(16)
        charts_layout.setColumnStretch(0, 1)
        charts_layout.setColumnStretch(1, 1)
        trend_card, self.trend_chart_view = _build_chart_card("روندِ ۶ ماهِ اخیر")
        charts_layout.addWidget(trend_card, 0, 0)
        top_card, self.top_chart_view = _build_chart_card(party_title)
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
        _render_bar_chart(self.trend_chart_view, labels, values, "مبلغ")

        top = dashboard_service.top_counterparties(company_id, self._document_type_code)
        _render_donut_chart(self.top_chart_view, top)


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
        outer.addStretch(1)

    def refresh(self) -> None:
        company_id = _company_id()
        self.card_total.refresh_theme(theme.ACCENT)
        self.card_active.refresh_theme(theme.CHART_TEAL)
        summary = dashboard_service.hr_summary(company_id)
        self.card_total.set_value(summary.total_employees)
        self.card_active.set_value(summary.active_employees)


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
        self.tabs.addTab(self._accounting_tab, "حسابداری")
        self._treasury_tab = _TreasuryTab()
        self.tabs.addTab(self._treasury_tab, "خزانه‌داری")
        self._inventory_tab = _InventoryTab()
        self.tabs.addTab(self._inventory_tab, "انبار")
        self._sales_tab = _CommercialTab("SALES_INVOICE", "فروشِ این ماه", "پُرفروش‌ترین مشتریان")
        self.tabs.addTab(self._sales_tab, "فروش")
        self._purchase_tab = _CommercialTab("PURCHASE_INVOICE", "خریدِ این ماه", "پُرخریدترین تامین‌کنندگان")
        self.tabs.addTab(self._purchase_tab, "خرید")
        self._hr_tab = _HrTab()
        self.tabs.addTab(self._hr_tab, "منابعِ‌انسانی")

        self._tabs_in_order = [
            self._overview_tab, self._accounting_tab, self._treasury_tab, self._inventory_tab,
            self._sales_tab, self._purchase_tab, self._hr_tab,
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

    def refresh(self) -> None:
        """طبقِ بازطراحیِ تب‌به‌تب: فقط تبِ فعلاً فعال رفرش می‌شود -- نه
        هر هفت تب هربار که کاربر داشبورد را باز می‌کند (کارایی)."""
        self._refresh_tab(self.tabs.currentIndex())

    def _refresh_tab(self, index: int) -> None:
        if 0 <= index < len(self._tabs_in_order):
            self._tabs_in_order[index].refresh()
