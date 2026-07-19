"""پوسته‌ی اصلی اپ: نوار کناری + نوار بالا + محتوای ماژول جاری.

نکته‌ی مهم درباره‌ی فهرست ماژول‌ها: طبق docs/ui-ux-guidelines.md بخش ۵، منبع
حقیقتِ منو باید sec.modules/sec.menus در دیتابیس باشد، نه کد. در این مرحله
(چون هنوز صفحه‌ای برای مدیریت ماژول/منو نساخته‌ایم و آن جدول‌ها خالی‌اند)
فهرست پایین موقتاً در پایتون هاردکد شده تا ساخت پوسته‌ی اصلی معطل یک
ابزار مدیریت منو نماند؛ وقتی sec.modules پر شد، این تابع باید با یک کوئری
به دیتابیس جایگزین شود.
"""

from __future__ import annotations

import os

from kivy.lang import Builder
from kivymd.uix.screen import MDScreen
from kivymd.uix.screenmanager import MDScreenManager

from peecha import session
from peecha.ui.rtl import shape

_KV_PATH = os.path.join(os.path.dirname(__file__), "shell.kv")
Builder.load_file(_KV_PATH)

# TODO(موقت): جایگزینی با کوئری روی sec.modules/sec.menus وقتی صفحه‌ی مدیریت منو ساخته شد
NAV_ITEMS = [
    {"code": "dashboard", "label": "داشبورد", "icon": "view-dashboard-outline", "screen": "dashboard"},
    {"code": "GL", "label": "مالی و حسابداری", "icon": "cash-multiple", "screen": "chart_of_accounts"},
    {"code": "INV", "label": "انبار و موجودی", "icon": "package-variant-closed", "screen": None},
    {"code": "SALES", "label": "فروش و بازاریابی", "icon": "cart-outline", "screen": None},
    {"code": "PURCH", "label": "خرید و تدارکات", "icon": "truck-outline", "screen": None},
    {"code": "HR", "label": "منابع انسانی", "icon": "account-group-outline", "screen": None},
    {"code": "INVOICES", "label": "فاکتورها", "icon": "receipt-text-outline", "screen": None},
    {"code": "REPORTS", "label": "گزارش‌ها", "icon": "chart-bar", "screen": None},
]


class ShellScreen(MDScreen):
    def on_pre_enter(self, *args):
        if not self.ids.content_manager.screen_names:
            self._build_content_screens()
        if not self.ids.nav_list.children:
            self._build_nav_items()
        self.ids.user_label.text = shape(session.current_user.full_name if session.current_user else "")
        self._select_nav("dashboard")

    def _build_content_screens(self) -> None:
        from peecha.ui.screens.chart_of_accounts import ChartOfAccountsScreen  # noqa: PLC0415
        from peecha.ui.screens.dashboard import DashboardScreen  # noqa: PLC0415
        from peecha.ui.screens.journal_entry import JournalEntryScreen  # noqa: PLC0415
        from peecha.ui.screens.placeholder import PlaceholderScreen  # noqa: PLC0415

        content: MDScreenManager = self.ids.content_manager
        content.add_widget(DashboardScreen())
        content.add_widget(ChartOfAccountsScreen())
        content.add_widget(JournalEntryScreen())
        content.add_widget(PlaceholderScreen())

    def _build_nav_items(self) -> None:
        from peecha.ui.widgets import PNavItem  # noqa: PLC0415

        for item in NAV_ITEMS:
            nav_item = PNavItem(icon=item["icon"], text=shape(item["label"]))
            nav_item.bind(on_release=lambda _inst, code=item["code"]: self._select_nav(code))
            self.ids.nav_list.add_widget(nav_item)

    def _select_nav(self, code: str) -> None:
        content: MDScreenManager = self.ids.content_manager
        item = next((i for i in NAV_ITEMS if i["code"] == code), None)
        if item is None:
            return

        for widget, nav_item in zip(NAV_ITEMS, self.ids.nav_list.children[::-1], strict=True):
            nav_item.selected = widget["code"] == code

        target_screen_name = item["screen"] or "placeholder"
        if target_screen_name == "placeholder":
            content.get_screen("placeholder").set_module_name(item["label"])
        content.current = target_screen_name

    def toggle_theme(self) -> None:
        from kivymd.app import MDApp  # noqa: PLC0415

        md_app = MDApp.get_running_app()
        md_app.theme_cls.theme_style = "Dark" if md_app.theme_cls.theme_style == "Light" else "Light"

    def log_out(self) -> None:
        session.log_out()
        self.manager.current = "login"
