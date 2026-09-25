"""پخشِ کالا -- طبقِ درخواستِ صریحِ کاربر («۳ ماژول: پخشِ سرد با
سفارش‌گیری، پخشِ گرم، سفارشِ موبایل») ولی هم‌زمان طبقِ محدودیتِ صریحِ
همان کاربر («منوها شلوغ نشه، تنظیمات هم جدا باشه»): همهٔ ماژول‌هایِ
ERP-محور (اسنادِ گرم، برنامهٔ مراجعه، بارگیریِ خودرو، ویزیت‌ها،
پروموشن‌ها) زیرِ یک آیتمِ ناوبریِ واحد با تب، هم‌الگو با
commercial_online_sales_hub.py -- به‌جایِ چند آیتمِ جداگانه در منویِ
اصلی. ماژولِ سومِ کاربر (اپِ سفارشِ موبایل) نیازمندِ یک تصمیمِ
معماریِ جداگانه (API/Offline-Sync) است و به‌مرور در R131/R132 اضافه
می‌شود.

طبقِ درخواستِ صریحِ بعدیِ کاربر («قسمتِ پخشِ سرد جدا باید باشه، فرمِ جدا
براش درست کن»): روالِ کاملِ پخشِ سرد (سفارش/تاییدِ انبار و توزین/تیمِ
پخش) از این‌جا بیرون رفت و آیتمِ ناوبریِ مستقلِ خودش را گرفت
(cold_distribution.py) -- این فرم فقط پخشِ گرم و زیرساختِ میدانیِ
مشترک را نگه می‌دارد."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from peecha.ui.screens.commercial_documents_list import CommercialDocumentsListScreen
from peecha.ui.screens.customer_visits import CustomerVisitsScreen
from peecha.ui.screens.field_sales_dashboard import FieldSalesDashboardScreen
from peecha.ui.screens.promotion_rules import PromotionRulesScreen
from peecha.ui.screens.sms_marketing import SmsMarketingScreen
from peecha.ui.screens.telesales import TelesalesScreen
from peecha.ui.screens.vehicle_loading import VehicleLoadingScreen
from peecha.ui.screens.vehicle_team import VehicleTeamScreen
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
        self.van_sales_tab = CommercialDocumentsListScreen(
            main_window, type_filter_codes=("SALES_ORDER", "SALES_INVOICE"), channel_type_code="VAN_SALES",
            title_override="اسنادِ پخشِ گرم (فروشِ خودرویی)",
        )
        self.tabs.addTab(self.van_sales_tab, "پخشِ گرم (فروشِ خودرویی)")
        # طبقِ درخواستِ صریحِ کاربر: پخشِ سرد از سه مسیر سفارش می‌گیرد --
        # عمده (حالا در آیتمِ مستقلِ «پخشِ سرد»، تبِ «سفارش‌ها»)، موبایلی
        # (R131/R132)، و این‌جا تلفنی؛ فهرستِ مشتریانِ ویزیتورِ واردشده
        # (مقیم یا تلفنی، فرقی ندارد) با امکانِ یادداشت/معین‌حساب/ثبتِ
        # سفارش از همین‌جا -- سفارشِ ثبت‌شده هم مثلِ بقیه، از آیتمِ
        # «پخشِ سرد» پیگیری/تایید/تبدیل می‌شود.
        self.tele_sales_tab = TelesalesScreen(main_window)
        self.tabs.addTab(self.tele_sales_tab, "فروشِ تلفنی")
        # طبقِ نقشه‌راهِ تاییدشده (R130): مدیریتِ زیرساختِ میدانیِ ساخته‌شده
        # در R129 -- همه زیرِ همین یک منو، نه آیتم‌هایِ جداگانه.
        self.visit_plans_tab = VisitPlansScreen()
        self.tabs.addTab(self.visit_plans_tab, "برنامهٔ مراجعه")
        self.vehicle_loading_tab = VehicleLoadingScreen()
        self.tabs.addTab(self.vehicle_loading_tab, "بارگیریِ خودرو")
        # طبقِ درخواستِ صریحِ کاربر (فازِ ۲ از پخشِ گرم): راننده/ویزیتور/
        # موزعِ هر خودرو.
        self.vehicle_team_tab = VehicleTeamScreen()
        self.tabs.addTab(self.vehicle_team_tab, "تیمِ خودرو")
        self.customer_visits_tab = CustomerVisitsScreen()
        self.tabs.addTab(self.customer_visits_tab, "ویزیت‌ها")
        self.promotion_rules_tab = PromotionRulesScreen()
        self.tabs.addTab(self.promotion_rules_tab, "پروموشن‌ها")
        # طبقِ نقشه‌راهِ تاییدشده (R134، آخرین فازِ این ماژول): داشبوردِ
        # سرپرست -- پوششِ ویزیت/عملکردِ فروش/رسیدِ تحویل/کسریِ بارگیری.
        self.dashboard_tab = FieldSalesDashboardScreen()
        self.tabs.addTab(self.dashboard_tab, "داشبوردِ سرپرست")
        # طبقِ درخواستِ صریح («یک تب برایِ بازاریابی و ارسالِ پیامکِ
        # زمان‌بندی‌شده»، R139).
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
