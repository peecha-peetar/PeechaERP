"""پخشِ کالا -- طبقِ درخواستِ صریحِ کاربر («۳ ماژول: پخشِ سرد با
سفارش‌گیری، پخشِ گرم، سفارشِ موبایل») ولی هم‌زمان طبقِ محدودیتِ صریحِ
همان کاربر («منوها شلوغ نشه، تنظیمات هم جدا باشه»): هر دو ماژولِ
ERP-محور (پخشِ سرد/گرم) زیرِ یک آیتمِ ناوبریِ واحد با تب، هم‌الگو با
commercial_online_sales_hub.py -- به‌جایِ دو آیتمِ جداگانه در منویِ
اصلی. ماژولِ سومِ کاربر (اپِ سفارشِ موبایل) نیازمندِ یک تصمیمِ
معماریِ جداگانه (API/Offline-Sync) است و در همین دور پیاده نشده."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from peecha.ui.screens.commercial_documents_list import CommercialDocumentsListScreen


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
        self.tabs.currentChanged.connect(self._refresh_tab_at)
        outer.addWidget(self.tabs, stretch=1)

    def _refresh_tab_at(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is not None and hasattr(widget, "refresh"):
            widget.refresh()

    def refresh(self) -> None:
        self._refresh_tab_at(self.tabs.currentIndex())
