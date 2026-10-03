"""پخشِ سرد -- طبقِ درخواستِ صریحِ کاربر («قسمتِ پخشِ سرد جدا باید باشه،
فرمِ جدا براش درست کن»): کلِ روالِ پخشِ سرد، مستقل از فرمِ چندمنظوره‌یِ
«پخشِ کالا» (که پخشِ گرم/تلفنی/ویزیت/بارگیریِ خودرو و... را دارد)، در
یک آیتمِ ناوبریِ جداگانه، با سه تب که دقیقاً مراحلِ اعلام‌شده را دنبال
می‌کنند:

۱) «سفارش‌ها» -- ثبتِ سفارش (و تبدیلِ سفارشِ تاییدشده به فاکتور، از
   همان دکمهٔ همیشگیِ فهرستِ اسناد).
۲) «تاییدِ انبار و توزین» -- گیتِ اجباریِ پیش از تبدیل به فاکتور.
۳) «تیمِ پخش» -- الصاقِ فاکتورهایِ ثبت‌نهایی‌شده به خودرو/راننده + گزارشِ
   چاپیِ لیستِ فاکتورها و جمعِ کالاها برایِ تحویل به راننده."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from peecha.ui.screens.commercial_documents_list import CommercialDocumentsListScreen
from peecha.ui.screens.distribution_team import DistributionTeamScreen
from peecha.ui.screens.pre_sales_fulfillment import PreSalesFulfillmentScreen


class ColdDistributionScreen(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("پخشِ سرد (سفارش‌گیری)")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.orders_tab = CommercialDocumentsListScreen(
            main_window, type_filter_codes=("SALES_ORDER", "SALES_INVOICE"), channel_type_code="PRE_SALES",
            title_override="سفارش‌ها و فاکتورهایِ پخشِ سرد",
        )
        self.tabs.addTab(self.orders_tab, "۱ - سفارش‌ها")
        self.fulfillment_tab = PreSalesFulfillmentScreen()
        self.tabs.addTab(self.fulfillment_tab, "۲ - تاییدِ انبار و توزین")
        self.distribution_team_tab = DistributionTeamScreen(main_window)
        self.tabs.addTab(self.distribution_team_tab, "۳ - تیمِ پخش")
        self.tabs.currentChanged.connect(self._refresh_tab_at)
        outer.addWidget(self.tabs, stretch=1)

    def _refresh_tab_at(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is not None and hasattr(widget, "refresh"):
            widget.refresh()

    def refresh(self) -> None:
        self._refresh_tab_at(self.tabs.currentIndex())
