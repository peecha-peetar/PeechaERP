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
#
# آیتم‌های سطح‌بالا ممکن است خودشان یک صفحه باشند («screen»)، یا یک گروه با
# چند زیرآیتم («children») — طبق درخواست کاربر، به‌جای تبِ داخلیِ جداگانه
# برای فرم‌های ماژول مالی/حسابداری (کدینگ حسابداری، صدور سند)، همه‌ی این
# میان‌برها مستقیم زیرِ «مالی و حسابداری» در نوار کناری دیده می‌شوند.
NAV_ITEMS = [
    {"code": "dashboard", "label": "داشبورد", "icon": "view-dashboard-outline", "screen": "dashboard"},
    {
        "code": "GL",
        "label": "مالی و حسابداری",
        "icon": "cash-multiple",
        "children": [
            {"code": "GL_COA", "label": "کدینگ حسابداری", "icon": "format-list-bulleted", "screen": "chart_of_accounts"},
            {"code": "GL_JE", "label": "صدور سند", "icon": "file-document-edit-outline", "screen": "journal_entry"},
        ],
    },
    {"code": "INV", "label": "انبار و موجودی", "icon": "package-variant-closed", "screen": None},
    {"code": "SALES", "label": "فروش و بازاریابی", "icon": "cart-outline", "screen": None},
    {"code": "PURCH", "label": "خرید و تدارکات", "icon": "truck-outline", "screen": None},
    {"code": "HR", "label": "منابع انسانی", "icon": "account-group-outline", "screen": None},
    {"code": "INVOICES", "label": "فاکتورها", "icon": "receipt-text-outline", "screen": None},
    {"code": "REPORTS", "label": "گزارش‌ها", "icon": "chart-bar", "screen": None},
    {
        "code": "SETTINGS",
        "label": "مدیریت سیستم",
        "icon": "cog-outline",
        "children": [
            {"code": "SET_LANG", "label": "زبان‌ها", "icon": "translate", "screen": "languages"},
            {"code": "SET_COMPANY", "label": "شرکت‌ها", "icon": "domain", "screen": "companies"},
            {"code": "SET_FY", "label": "سال‌های مالی", "icon": "calendar-blank-outline", "screen": "fiscal_years"},
            {"code": "SET_USERS", "label": "کاربران", "icon": "account-multiple-outline", "screen": "users"},
            {"code": "SET_ROLES", "label": "نقش‌ها و دسترسی‌ها", "icon": "shield-account-outline", "screen": "roles"},
        ],
    },
]


def _flatten_nav_items() -> list[dict]:
    """فهرست تخت (بدون تو در تو) از همه‌ی آیتم‌های قابل‌کلیک — هم آیتم‌های
    سطح‌بالای بدون فرزند، هم هرکدام از زیرآیتم‌های یک گروه؛ خودِ سرآیتمِ
    گروه‌دار (مثل «مالی و حسابداری») در این فهرست نیست چون خودش صفحه‌ای
    ندارد، فقط زیرآیتم‌هایش دارند."""
    flat: list[dict] = []
    for item in NAV_ITEMS:
        if "children" in item:
            flat.extend(item["children"])
        else:
            flat.append(item)
    return flat


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
        from peecha.ui.screens.companies import CompaniesScreen  # noqa: PLC0415
        from peecha.ui.screens.dashboard import DashboardScreen  # noqa: PLC0415
        from peecha.ui.screens.fiscal_years import FiscalYearsScreen  # noqa: PLC0415
        from peecha.ui.screens.journal_entry import JournalEntryScreen  # noqa: PLC0415
        from peecha.ui.screens.languages import LanguagesScreen  # noqa: PLC0415
        from peecha.ui.screens.placeholder import PlaceholderScreen  # noqa: PLC0415
        from peecha.ui.screens.roles import RolesScreen  # noqa: PLC0415
        from peecha.ui.screens.users import UsersScreen  # noqa: PLC0415

        content: MDScreenManager = self.ids.content_manager
        content.add_widget(DashboardScreen())
        content.add_widget(ChartOfAccountsScreen())
        content.add_widget(JournalEntryScreen())
        content.add_widget(LanguagesScreen())
        content.add_widget(CompaniesScreen())
        content.add_widget(FiscalYearsScreen())
        content.add_widget(UsersScreen())
        content.add_widget(RolesScreen())
        content.add_widget(PlaceholderScreen())

    def _build_nav_items(self) -> None:
        from peecha.ui.widgets import PNavGroupLabel, PNavItem  # noqa: PLC0415

        for item in NAV_ITEMS:
            if "children" in item:
                self.ids.nav_list.add_widget(PNavGroupLabel(icon=item["icon"], text=shape(item["label"])))
                for child in item["children"]:
                    nav_item = PNavItem(icon=child["icon"], text=shape(child["label"]), sub=True)
                    nav_item.bind(on_release=lambda _inst, code=child["code"]: self._select_nav(code))
                    self.ids.nav_list.add_widget(nav_item)
            else:
                nav_item = PNavItem(icon=item["icon"], text=shape(item["label"]))
                nav_item.bind(on_release=lambda _inst, code=item["code"]: self._select_nav(code))
                self.ids.nav_list.add_widget(nav_item)

    def _select_nav(self, code: str) -> None:
        content: MDScreenManager = self.ids.content_manager
        flat_items = _flatten_nav_items()
        item = next((i for i in flat_items if i["code"] == code), None)
        if item is None:
            return

        # نوار کناری هم سرآیتم‌های گروه (غیرقابل‌کلیک) و هم آیتم‌های قابل‌کلیک
        # را دارد؛ فقط آیتم‌های قابل‌کلیک را با flat_items جفت می‌کنیم.
        from peecha.ui.widgets import PNavItem  # noqa: PLC0415

        clickable_widgets = [w for w in self.ids.nav_list.children[::-1] if isinstance(w, PNavItem)]
        for widget, nav_item in zip(flat_items, clickable_widgets, strict=True):
            nav_item.selected = widget["code"] == code

        target_screen_name = item["screen"] or "placeholder"
        if target_screen_name == "placeholder":
            content.get_screen("placeholder").set_module_name(item["label"])
        content.current = target_screen_name

    def toggle_theme(self) -> None:
        from kivymd.app import MDApp  # noqa: PLC0415

        md_app = MDApp.get_running_app()
        md_app.theme_cls.theme_style = "Dark" if md_app.theme_cls.theme_style == "Light" else "Light"

    def on_leave(self, *args):
        # content_manager یک ScreenManagerِ تودرتوی جداست: وقتی خودِ پوسته
        # (shell) با خروج از حساب کاربری ترک می‌شود، on_leave خودش خودکار
        # به صفحه‌ی فعلیِ داخلِ content_manager نمی‌رسد — اگر آن صفحه
        # میانبرهای کیبورد بسته باشد (مثل کدینگ حسابداری/صدور سند)، بدون
        # این فراخوانیِ صریح، آن‌ها به Window بسته می‌مانند و بعد از خروج هم
        # فعال می‌مانند.
        current_screen = self.ids.content_manager.current_screen
        if current_screen is not None and hasattr(current_screen, "unbind_shortcuts"):
            current_screen.unbind_shortcuts()

    def log_out(self) -> None:
        session.log_out()
        self.manager.current = "login"
