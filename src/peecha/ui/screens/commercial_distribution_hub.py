"""پخشِ کالا -- طبقِ درخواستِ صریحِ کاربر («۳ ماژول: پخشِ سرد با
سفارش‌گیری، پخشِ گرم، سفارشِ موبایل») ولی هم‌زمان طبقِ محدودیتِ صریحِ
همان کاربر («منوها شلوغ نشه، تنظیمات هم جدا باشه»): همهٔ ماژول‌هایِ
ERP-محور (اسنادِ سرد/گرم، برنامهٔ مراجعه، بارگیریِ خودرو، ویزیت‌ها،
پروموشن‌ها) زیرِ یک آیتمِ ناوبریِ واحد با تب، هم‌الگو با
commercial_online_sales_hub.py -- به‌جایِ چند آیتمِ جداگانه در منویِ
اصلی. ماژولِ سومِ کاربر (اپِ سفارشِ موبایل) نیازمندِ یک تصمیمِ
معماریِ جداگانه (API/Offline-Sync) است و به‌مرور در R131/R132 اضافه
می‌شود."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from peecha.ui.screens.commercial_documents_list import CommercialDocumentsListScreen
from peecha.ui.screens.customer_visits import CustomerVisitsScreen
from peecha.ui.screens.field_sales_dashboard import FieldSalesDashboardScreen
from peecha.ui.screens.promotion_rules import PromotionRulesScreen
from peecha.ui.screens.vehicle_loading import VehicleLoadingScreen
from peecha.ui.screens.visit_plans import VisitPlansScreen


class CommercialDistributionHubScreen(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("پخشِ کالا")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.pre_sales_tab = CommercialDocumentsListScreen(
            main_window, type_filter_codes=("SALES_ORDER", "SALES_INVOICE"), channel_type_code="PRE_SALES",
            title_override="اسنادِ پخشِ سرد (سفارش‌گیری)",
        )
        self.tabs.addTab(self.pre_sales_tab, "پخشِ سرد (سفارش‌گیری)")
        self.van_sales_tab = CommercialDocumentsListScreen(
            main_window, type_filter_codes=("SALES_ORDER", "SALES_INVOICE"), channel_type_code="VAN_SALES",
            title_override="اسنادِ پخشِ گرم (فروشِ خودرویی)",
        )
        self.tabs.addTab(self.van_sales_tab, "پخشِ گرم (فروشِ خودرویی)")
        # طبقِ نقشه‌راهِ تاییدشده (R130): مدیریتِ زیرساختِ میدانیِ ساخته‌شده
        # در R129 -- همه زیرِ همین یک منو، نه آیتم‌هایِ جداگانه.
        self.visit_plans_tab = VisitPlansScreen()
        self.tabs.addTab(self.visit_plans_tab, "برنامهٔ مراجعه")
        self.vehicle_loading_tab = VehicleLoadingScreen()
        self.tabs.addTab(self.vehicle_loading_tab, "بارگیریِ خودرو")
        self.customer_visits_tab = CustomerVisitsScreen()
        self.tabs.addTab(self.customer_visits_tab, "ویزیت‌ها")
        self.promotion_rules_tab = PromotionRulesScreen()
        self.tabs.addTab(self.promotion_rules_tab, "پروموشن‌ها")
        # طبقِ نقشه‌راهِ تاییدشده (R134، آخرین فازِ این ماژول): داشبوردِ
        # سرپرست -- پوششِ ویزیت/عملکردِ فروش/رسیدِ تحویل/کسریِ بارگیری.
        self.dashboard_tab = FieldSalesDashboardScreen()
        self.tabs.addTab(self.dashboard_tab, "داشبوردِ سرپرست")
        self.tabs.currentChanged.connect(self._refresh_tab_at)
        outer.addWidget(self.tabs, stretch=1)

    def _refresh_tab_at(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is not None and hasattr(widget, "refresh"):
            widget.refresh()

    def refresh(self) -> None:
        self._refresh_tab_at(self.tabs.currentIndex())
