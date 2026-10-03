"""برنامه‌ریزیِ فروش -- طبقِ درخواستِ صریحِ کاربر («وقتی منویِ پخشِ گرم
اجرا می‌شود فقط تب‌هایِ مربوط به پخشِ گرم باز شود و بقیهٔ تب‌ها در
منویِ مربوط به خودشون ایجاد بشه»): این تب‌ها نه مخصوصِ پخشِ گرم‌اند
نه پخشِ سرد -- هردو کانال از همین برنامهٔ مراجعه/ویزیت/پروموشن/
داشبورد/بازاریابیِ مشترک استفاده می‌کنند، پس زیرِ آیتمِ ناوبریِ
مستقلِ خودشان جمع شدند (تا منوهای گرم/سرد شلوغ نشوند)."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from peecha.ui.screens.customer_visits import CustomerVisitsScreen
from peecha.ui.screens.field_sales_dashboard import FieldSalesDashboardScreen
from peecha.ui.screens.promotion_rules import PromotionRulesScreen
from peecha.ui.screens.sms_marketing import SmsMarketingScreen
from peecha.ui.screens.visit_plans import VisitPlansScreen


class SalesPlanningHubScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("برنامه‌ریزیِ فروش")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.visit_plans_tab = VisitPlansScreen()
        self.tabs.addTab(self.visit_plans_tab, "برنامهٔ مراجعه")
        self.customer_visits_tab = CustomerVisitsScreen()
        self.tabs.addTab(self.customer_visits_tab, "ویزیت‌ها")
        self.promotion_rules_tab = PromotionRulesScreen()
        self.tabs.addTab(self.promotion_rules_tab, "پروموشن‌ها")
        self.dashboard_tab = FieldSalesDashboardScreen()
        self.tabs.addTab(self.dashboard_tab, "داشبوردِ سرپرست")
        self.marketing_tab = SmsMarketingScreen()
        self.tabs.addTab(self.marketing_tab, "بازاریابی")
        self.tabs.currentChanged.connect(self._refresh_tab_at)
        outer.addWidget(self.tabs, stretch=1)

    def _refresh_tab_at(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is not None and hasattr(widget, "refresh"):
            widget.refresh()

    def refresh(self) -> None:
        self._refresh_tab_at(self.tabs.currentIndex())
