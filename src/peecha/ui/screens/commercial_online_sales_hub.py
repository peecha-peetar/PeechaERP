"""فروشِ اینترنتی -- طبقِ بازخوردِ صریحِ کاربر («منویِ اصلی شلوغ شده،
فقط فروشِ اینترنتی باید آنجا باشد»): سفارش‌ها + تقویمِ محتوا/پستِ خودکار
+ سینکِ CMS + مرکزِ رسانه + نگهبانِ اتصال، همگی زیرِ یک منو و یک فرم با
تب‌هایِ مختلف -- به‌جایِ پنج آیتمِ جداگانه در منویِ اصلی."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from peecha.ui.screens.commercial_cms import CommercialCmsScreen
from peecha.ui.screens.commercial_coupons import CommercialCouponsScreen
from peecha.ui.screens.commercial_documents_list import CommercialDocumentsListScreen
from peecha.ui.screens.commercial_reviews import CommercialReviewsScreen
from peecha.ui.screens.commercial_social import CommercialSocialScreen
from peecha.ui.screens.connectivity_guard import ConnectivityGuardScreen
from peecha.ui.screens.media_center import MediaCenterScreen
from peecha.ui.screens.online_marketing import OnlineMarketingScreen
from peecha.ui.screens.online_store_advisor import OnlineStoreAdvisorScreen
from peecha.ui.screens.smart_publish_settings import SmartPublishSettingsScreen


class CommercialOnlineSalesHubScreen(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("فروشِ اینترنتی")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.orders_tab = CommercialDocumentsListScreen(
            main_window, type_filter_codes=("SALES_ORDER",), channel_type_code="ONLINE",
            title_override="سفارش‌هایِ فروشِ اینترنتی",
        )
        self.tabs.addTab(self.orders_tab, "سفارش‌ها")
        self.social_tab = CommercialSocialScreen()
        self.tabs.addTab(self.social_tab, "تقویمِ محتوا و پستِ خودکار")
        self.cms_tab = CommercialCmsScreen()
        self.tabs.addTab(self.cms_tab, "سینکِ محتوا با CMS")
        self.media_tab = MediaCenterScreen()
        self.tabs.addTab(self.media_tab, "مرکزِ رسانه")
        self.guard_tab = ConnectivityGuardScreen()
        self.tabs.addTab(self.guard_tab, "نگهبانِ اتصال و سلامتِ سایت")
        self.coupons_tab = CommercialCouponsScreen()
        self.tabs.addTab(self.coupons_tab, "کوپن/کدِ تخفیف")
        self.reviews_tab = CommercialReviewsScreen()
        self.tabs.addTab(self.reviews_tab, "نظراتِ مشتریان")
        self.advisor_tab = OnlineStoreAdvisorScreen()
        self.tabs.addTab(self.advisor_tab, "دستیارِ فروشگاه")
        self.marketing_tab = OnlineMarketingScreen()
        self.tabs.addTab(self.marketing_tab, "بازاریابی")
        self.smart_publish_tab = SmartPublishSettingsScreen()
        self.tabs.addTab(self.smart_publish_tab, "Smart Publish")
        self.tabs.currentChanged.connect(self._refresh_tab_at)
        outer.addWidget(self.tabs, stretch=1)

    def _refresh_tab_at(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is not None and hasattr(widget, "refresh"):
            widget.refresh()

    def refresh(self) -> None:
        self._refresh_tab_at(self.tabs.currentIndex())
