"""پخشِ گرم (فروشِ خودرویی) -- طبقِ درخواستِ صریحِ کاربر («وقتی منویِ
پخشِ گرم اجرا می‌شود فقط تب‌هایِ مربوط به پخشِ گرم باز شود و بقیهٔ
تب‌ها در منویِ مربوط به خودشون ایجاد بشه»): این فرم دیگر زیرساختِ
میدانیِ مشترک/نامرتبط را ندارد -- فقط چهار تبی که واقعاً مخصوصِ
پخشِ گرم (خودرو/فروشِ خودرویی) هستند. فروشِ تلفنی به آیتمِ ناوبریِ
مستقلِ خودش (commercial_telesales) رفت؛ برنامهٔ مراجعه/ویزیت‌ها/
پروموشن‌ها/داشبوردِ سرپرست/بازاریابی -- که هیچ‌کدام مخصوصِ پخشِ گرم
یا سرد نیستند -- به آیتمِ تازهٔ «برنامه‌ریزیِ فروش» (sales_planning_hub)
منتقل شدند."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from peecha.ui.screens.commercial_documents_list import CommercialDocumentsListScreen
from peecha.ui.screens.vehicle_loading import VehicleLoadingScreen
from peecha.ui.screens.vehicle_settlement import VehicleSettlementScreen
from peecha.ui.screens.vehicle_team import VehicleTeamScreen


class CommercialDistributionHubScreen(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        title = QLabel("پخشِ گرم (فروشِ خودرویی)")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.van_sales_tab = CommercialDocumentsListScreen(
            main_window, type_filter_codes=("SALES_ORDER", "SALES_INVOICE"), channel_type_code="VAN_SALES",
            title_override="اسنادِ پخشِ گرم (فروشِ خودرویی)",
        )
        self.tabs.addTab(self.van_sales_tab, "اسناد")
        self.vehicle_loading_tab = VehicleLoadingScreen()
        self.tabs.addTab(self.vehicle_loading_tab, "بارگیریِ خودرو")
        # طبقِ درخواستِ صریحِ کاربر (فازِ ۲ از پخشِ گرم): راننده/ویزیتور/
        # موزعِ هر خودرو.
        self.vehicle_team_tab = VehicleTeamScreen()
        self.tabs.addTab(self.vehicle_team_tab, "تیمِ خودرو")
        # طبقِ درخواستِ صریحِ کاربر («تسویه آخر روز باید بصورت انتخابی به
        # یک نفر از ۳ نقش واگذار بشه و به تاییدِ انبار و حسابداری برسه»).
        self.vehicle_settlement_tab = VehicleSettlementScreen()
        self.tabs.addTab(self.vehicle_settlement_tab, "تسویهٔ خودرو")
        self.tabs.currentChanged.connect(self._refresh_tab_at)
        outer.addWidget(self.tabs, stretch=1)

    def _refresh_tab_at(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is not None and hasattr(widget, "refresh"):
            widget.refresh()

    def refresh(self) -> None:
        self._refresh_tab_at(self.tabs.currentIndex())
