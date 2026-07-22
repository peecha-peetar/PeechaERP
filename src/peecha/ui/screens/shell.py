"""پوسته‌ی اصلی اپ: نوار کناری + نوار بالا + محتوای ماژول جاری.

نکته‌ی مهم درباره‌ی فهرست ماژول‌ها: طبق docs/ui-ux-guidelines.md بخش ۵، منبع
حقیقتِ منو باید sec.modules/sec.menus در دیتابیس باشد، نه کد. در این مرحله
(چون هنوز صفحه‌ای برای مدیریت ماژول/منو نساخته‌ایم و آن جدول‌ها خالی‌اند)
فهرست پایین موقتاً در پایتون هاردکد شده تا ساخت پوسته‌ی اصلی معطل یک
ابزار مدیریت منو نماند؛ وقتی sec.modules پر شد، این تابع باید با یک کوئری
به دیتابیس جایگزین شود.
"""

from __future__ import annotations

import datetime
import os

from kivy.lang import Builder
from kivy.properties import BooleanProperty
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen
from kivymd.uix.screenmanager import MDScreenManager

from peecha import session
from peecha.services import companies as companies_service
from peecha.services import fiscal_years as fiscal_years_service
from peecha.services import languages as languages_service
from peecha.ui import numerals
from peecha.ui.i18n import tr
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
            {"code": "GL_CUSTOMERS", "label": "مشتریان", "icon": "account-cash-outline", "screen": "customers"},
            {"code": "GL_SUPPLIERS", "label": "تامین‌کنندگان", "icon": "truck-outline", "screen": "suppliers"},
            {"code": "GL_PERSONNEL", "label": "پرسنل", "icon": "badge-account-outline", "screen": "personnel"},
            {
                "code": "GL_JE_LIST",
                "label": "اسناد حسابداری",
                "icon": "file-document-multiple-outline",
                "screen": "journal_entries_list",
            },
            {"code": "GL_JE", "label": "صدور سند جدید", "icon": "file-document-edit-outline", "screen": "journal_entry"},
            {"code": "GL_DIM", "label": "مراکز هزینه و ابعادِ تفصیلی", "icon": "shape-outline", "screen": "detail_dimensions"},
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
            {"code": "SET_CURRENCY", "label": "ارزها", "icon": "cash-multiple", "screen": "currencies"},
            {"code": "SET_COMPANY", "label": "شرکت‌ها", "icon": "domain", "screen": "companies"},
            {"code": "SET_FY", "label": "سال‌های مالی", "icon": "calendar-blank-outline", "screen": "fiscal_years"},
            {"code": "SET_USERS", "label": "کاربران", "icon": "account-multiple-outline", "screen": "users"},
            {"code": "SET_ROLES", "label": "نقش‌ها و دسترسی‌ها", "icon": "shield-account-outline", "screen": "roles"},
            {"code": "SET_FIELD_LABELS", "label": "عنوانِ فیلدها", "icon": "form-textbox", "screen": "field_labels"},
            {"code": "SET_TRANSLATIONS", "label": "ترجمه‌ها", "icon": "web", "screen": "translations"},
            {"code": "SET_AUDIT_LOG", "label": "ردِ حسابرسی", "icon": "history", "screen": "audit_log"},
        ],
    },
]


# طبقِ بازطراحیِ الهام‌گرفته از ریبونِ نرم‌افزارهای حسابداریِ کلاسیک: زیرِ
# نوارِ بالا یک ردیفِ افقیِ آیکون+برچسبِ کوتاه برایِ پراستفاده‌ترین صفحات
# (نه همه‌ی صفحات — آن‌ها همچنان در منویِ درختیِ نوار کناری هستند).
_RIBBON_CODES = [
    "dashboard", "GL_COA", "GL_JE_LIST", "GL_JE", "GL_CUSTOMERS", "GL_SUPPLIERS", "GL_PERSONNEL", "SET_CURRENCY",
    "SET_AUDIT_LOG",
]
_RIBBON_LABEL_OVERRIDES = {
    "GL_COA": "کدینگ",
    "GL_JE_LIST": "اسناد",
    "GL_JE": "سند جدید",
    "SET_AUDIT_LOG": "رد حسابرسی",
}


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
    # طبق درخواستِ صریح: نوار کناری وقتی لازم نیست خودکار جمع می‌شود تا
    # فضای بیشتری برای فرم‌ها بماند — پیش‌فرضِ اولیه جمع‌شده است.
    sidebar_collapsed = BooleanProperty(True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._company_options: list[companies_service.CompanyRow] = []
        self._fiscal_year_options: list[fiscal_years_service.FiscalYearRow] = []
        self._language_options: list[languages_service.LanguageRow] = []
        self._menu: MDDropdownMenu | None = None
        self._group_children: dict[str, list] = {}
        self._group_labels: dict[str, object] = {}
        self._ribbon_buttons: dict[str, object] = {}

    def on_pre_enter(self, *args):
        if not self.ids.content_manager.screen_names:
            self._build_content_screens()
            self._sync_translation_files()
        if not self.ids.nav_list.children:
            self._build_nav_items()
        if not self.ids.ribbon_list.children:
            self._build_ribbon()
        self.ids.user_label.text = shape(session.current_user.full_name if session.current_user else "")
        self._load_context_switcher()
        self._select_nav("dashboard")

    def _build_ribbon(self) -> None:
        from peecha.ui.widgets import PRibbonButton  # noqa: PLC0415

        self._ribbon_buttons: dict[str, PRibbonButton] = {}
        flat_by_code = {item["code"]: item for item in _flatten_nav_items()}
        for code in _RIBBON_CODES:
            item = flat_by_code.get(code)
            if item is None:
                continue
            label = _RIBBON_LABEL_OVERRIDES.get(code, item["label"])
            button = PRibbonButton(icon=item["icon"], text=shape(tr(label)))
            button.bind(on_release=lambda _inst, c=code: self._select_nav(c))
            self.ids.ribbon_list.add_widget(button)
            self._ribbon_buttons[code] = button

    def _build_content_screens(self) -> None:
        from peecha.ui.screens.audit_log import AuditLogScreen  # noqa: PLC0415
        from peecha.ui.screens.chart_of_accounts import ChartOfAccountsScreen  # noqa: PLC0415
        from peecha.ui.screens.companies import CompaniesScreen  # noqa: PLC0415
        from peecha.ui.screens.currencies import CurrenciesScreen  # noqa: PLC0415
        from peecha.ui.screens.dashboard import DashboardScreen  # noqa: PLC0415
        from peecha.ui.screens.detail_dimensions import DetailDimensionsScreen  # noqa: PLC0415
        from peecha.ui.screens.field_labels import FieldLabelsScreen  # noqa: PLC0415
        from peecha.ui.screens.fiscal_years import FiscalYearsScreen  # noqa: PLC0415
        from peecha.ui.screens.journal_entries_list import JournalEntriesListScreen  # noqa: PLC0415
        from peecha.ui.screens.journal_entry import JournalEntryScreen  # noqa: PLC0415
        from peecha.ui.screens.languages import LanguagesScreen  # noqa: PLC0415
        from peecha.ui.screens.person_group_screens import (  # noqa: PLC0415
            CustomersScreen,
            PersonnelScreen,
            SuppliersScreen,
        )
        from peecha.ui.screens.placeholder import PlaceholderScreen  # noqa: PLC0415
        from peecha.ui.screens.roles import RolesScreen  # noqa: PLC0415
        from peecha.ui.screens.translations import TranslationsScreen  # noqa: PLC0415
        from peecha.ui.screens.users import UsersScreen  # noqa: PLC0415

        content: MDScreenManager = self.ids.content_manager
        content.add_widget(DashboardScreen())
        content.add_widget(ChartOfAccountsScreen())
        content.add_widget(CustomersScreen())
        content.add_widget(SuppliersScreen())
        content.add_widget(PersonnelScreen())
        content.add_widget(JournalEntriesListScreen())
        content.add_widget(JournalEntryScreen())
        content.add_widget(DetailDimensionsScreen())
        content.add_widget(LanguagesScreen())
        content.add_widget(CurrenciesScreen())
        content.add_widget(CompaniesScreen())
        content.add_widget(FiscalYearsScreen())
        content.add_widget(TranslationsScreen())
        content.add_widget(AuditLogScreen())
        content.add_widget(UsersScreen())
        content.add_widget(RolesScreen())
        content.add_widget(FieldLabelsScreen())
        content.add_widget(PlaceholderScreen())

    def _sync_translation_files(self) -> None:
        # طبق درخواستِ صریح: «در آینده هم اگر فرمی اضافه میشه ترجمه بشه» —
        # هر بار برنامه بالا می‌آید، فایلِ ترجمه‌ی همه‌ی زبان‌های غیرِ
        # پیش‌فرضِ موجود با فهرستِ فعلیِ متن‌های قابل‌ترجمه (که ممکن است
        # از آخرین‌بار رشدکرده باشد) هم‌گام می‌شود.
        from peecha.services import i18n_translations as i18n_translations_service  # noqa: PLC0415

        non_default_codes = [lang.code for lang in languages_service.list_languages() if not lang.is_default]
        if non_default_codes:
            i18n_translations_service.regenerate_all(non_default_codes)

    def _build_nav_items(self) -> None:
        from peecha.ui.widgets import PNavGroupLabel, PNavItem  # noqa: PLC0415

        self._group_children: dict[str, list] = {}
        self._group_labels: dict[str, PNavGroupLabel] = {}

        for item in NAV_ITEMS:
            if "children" in item:
                group_label = PNavGroupLabel(
                    icon=item["icon"], text=shape(tr(item["label"])), expanded=False, collapsed=self.sidebar_collapsed
                )
                group_label.bind(on_release=lambda _inst, code=item["code"]: self._toggle_group(code))
                self.ids.nav_list.add_widget(group_label)
                self._group_labels[item["code"]] = group_label

                children_widgets = []
                for child in item["children"]:
                    nav_item = PNavItem(
                        icon=child["icon"], text=shape(tr(child["label"])), sub=True, collapsed=self.sidebar_collapsed
                    )
                    nav_item.bind(on_release=lambda _inst, code=child["code"]: self._select_nav(code))
                    self.ids.nav_list.add_widget(nav_item)
                    children_widgets.append(nav_item)
                self._group_children[item["code"]] = children_widgets
                self._set_group_expanded(item["code"], expanded=False)
            else:
                nav_item = PNavItem(icon=item["icon"], text=shape(tr(item["label"])), collapsed=self.sidebar_collapsed)
                nav_item.bind(on_release=lambda _inst, code=item["code"]: self._select_nav(code))
                self.ids.nav_list.add_widget(nav_item)

    def toggle_sidebar(self) -> None:
        self.sidebar_collapsed = not self.sidebar_collapsed
        from peecha.ui.widgets import PNavGroupLabel, PNavItem  # noqa: PLC0415

        for widget in self.ids.nav_list.children:
            if isinstance(widget, (PNavItem, PNavGroupLabel)):
                widget.collapsed = self.sidebar_collapsed

    def _set_group_expanded(self, group_code: str, *, expanded: bool) -> None:
        label = self._group_labels.get(group_code)
        if label is not None:
            label.expanded = expanded
        for nav_item in self._group_children.get(group_code, []):
            if expanded:
                nav_item.disabled = False
                nav_item.opacity = 1
                nav_item.size_hint_y = None
                nav_item.height = "40dp" if nav_item.sub else "44dp"
            else:
                nav_item.disabled = True
                nav_item.opacity = 0
                nav_item.size_hint_y = None
                nav_item.height = 0

    def _toggle_group(self, group_code: str) -> None:
        label = self._group_labels.get(group_code)
        if label is None:
            return
        self._set_group_expanded(group_code, expanded=not label.expanded)

    def _expand_group_containing(self, code: str) -> None:
        """گروهی که این کد در آن است را باز می‌کند — مثلاً وقتی مستقیم به
        زیرآیتمِ یک گروهِ جمع‌شده رفته می‌شود (نه از طریق کلیکِ خودِ کاربر
        روی سرآیتمِ گروه)، تا زیرآیتمِ فعال از دیدِ کاربر پنهان نماند."""
        for item in NAV_ITEMS:
            if "children" in item and any(child["code"] == code for child in item["children"]):
                self._set_group_expanded(item["code"], expanded=True)
                return

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
        self._expand_group_containing(code)

        for ribbon_code, button in self._ribbon_buttons.items():
            button.selected = ribbon_code == code

        target_screen_name = item["screen"] or "placeholder"
        if target_screen_name == "placeholder":
            content.get_screen("placeholder").set_module_name(item["label"])
        content.current = target_screen_name

    def open_screen(self, code: str, *, then=None) -> None:
        """رفتن به یک ماژول از داخلِ خودِ یک صفحه‌ی محتوا (نه از کلیکِ کاربر
        روی نوار کناری) — مثلاً وقتی فهرستِ اسناد با کلیک روی یک ردیف کاربر
        را به فرمِ صدور سند برای ویرایش می‌برد. اگر then داده شود، بلافاصله
        بعدِ رفتن به صفحه‌ی مقصد با خودِ آن صفحه صدا زده می‌شود."""
        self._select_nav(code)
        if then is not None:
            then(self.ids.content_manager.current_screen)

    # --- سوییچرِ «شرکتِ فعال / سالِ مالیِ فعال / زبان» در هدر -------------------
    # طبق درخواستِ صریح کاربر: جایی مشخص (اینجا هدر) که کاربر از میانِ
    # شرکت‌هایی که خودش دسترسی دارد (sec.user_companies) شرکتِ فعال را
    # انتخاب کند؛ سالِ مالی و زبان هم به همین ترتیب. تعویضِ شرکت باید صفحه‌ی
    # فعلی را هم دوباره از دیتابیس بار کند (چون کدینگ حسابداری/سند/... همه
    # به company_id وابسته‌اند).

    def _load_context_switcher(self) -> None:
        if session.current_user is None:
            return
        self._company_options = companies_service.list_companies_for_user(session.current_user.user_id)
        if session.current_company is None or not any(
            c.company_id == session.current_company.company_id for c in self._company_options
        ):
            first = self._company_options[0] if self._company_options else None
            session.current_company = companies_service.get_company_model(first.company_id) if first else None
        self._refresh_company_text()
        self._reload_fiscal_years()
        self._load_languages()

    def _refresh_company_text(self) -> None:
        text = session.current_company.display_name if session.current_company else tr("— بدون شرکت —")
        self.ids.company_button.text = shape(text)

    def open_company_menu(self) -> None:
        if not self._company_options:
            return
        from peecha.ui.widgets import open_rtl_dropdown  # noqa: PLC0415

        items = [
            {
                "text": shape(c.display_name),
                "on_release": lambda cid=c.company_id: (self._menu.dismiss(), self._select_company(cid)),
            }
            for c in self._company_options
        ]
        self._menu = open_rtl_dropdown(self.ids.company_button, items, width_mult=3)

    def _select_company(self, company_id: int) -> None:
        if session.current_company is not None and session.current_company.company_id == company_id:
            return
        session.current_company = companies_service.get_company_model(company_id)
        self._refresh_company_text()
        self._reload_fiscal_years()
        self._refresh_current_screen()

    def _reload_fiscal_years(self) -> None:
        if session.current_company is None:
            self._fiscal_year_options = []
            session.current_fiscal_year = None
        else:
            self._fiscal_year_options = fiscal_years_service.list_fiscal_years(session.current_company.company_id)
            session.current_fiscal_year = fiscal_years_service.pick_current(
                session.current_company.company_id, datetime.date.today()
            )
        self._refresh_fiscal_year_text()

    def _refresh_fiscal_year_text(self) -> None:
        fy = session.current_fiscal_year
        text = numerals.to_persian_digits(fy.code) if fy else tr("— سالی تعریف نشده —")
        self.ids.fiscal_year_button.text = shape(text)

    def open_fiscal_year_menu(self) -> None:
        if not self._fiscal_year_options:
            return
        from peecha.ui.widgets import open_rtl_dropdown  # noqa: PLC0415

        items = [
            {
                "text": shape(numerals.to_persian_digits(fy.code)),
                "on_release": lambda fy_id=fy.fiscal_year_id: (self._menu.dismiss(), self._select_fiscal_year(fy_id)),
            }
            for fy in self._fiscal_year_options
        ]
        self._menu = open_rtl_dropdown(self.ids.fiscal_year_button, items, width_mult=3)

    def _select_fiscal_year(self, fiscal_year_id: int) -> None:
        fy = next((f for f in self._fiscal_year_options if f.fiscal_year_id == fiscal_year_id), None)
        if fy is None:
            return
        session.current_fiscal_year = fy
        self._refresh_fiscal_year_text()

    def _load_languages(self) -> None:
        self._language_options = languages_service.list_languages()
        if session.current_language is None or not any(
            l.language_id == session.current_language.language_id for l in self._language_options
        ):
            preferred_id = (
                session.current_user.default_language_id
                if session.current_user and session.current_user.default_language_id
                else (session.current_company.default_language_id if session.current_company else None)
            )
            chosen = next((l for l in self._language_options if l.language_id == preferred_id), None)
            chosen = chosen or next((l for l in self._language_options if l.is_default), None)
            chosen = chosen or (self._language_options[0] if self._language_options else None)
            self._set_current_language(chosen)
        self._refresh_language_text()

    def _refresh_language_text(self) -> None:
        text = session.current_language.native_name if session.current_language else tr("— بدون زبان —")
        self.ids.language_button.text = shape(text)

    def open_language_menu(self) -> None:
        if not self._language_options:
            return
        from peecha.ui.widgets import open_rtl_dropdown  # noqa: PLC0415

        items = [
            {
                "text": shape(l.native_name),
                "on_release": lambda lid=l.language_id: (self._menu.dismiss(), self._select_language(lid)),
            }
            for l in self._language_options
        ]
        self._menu = open_rtl_dropdown(self.ids.language_button, items, width_mult=3)

    def _select_language(self, language_id: int) -> None:
        row = next((l for l in self._language_options if l.language_id == language_id), None)
        if row is None:
            return
        self._set_current_language(row)
        self._refresh_language_text()
        self._refresh_nav_item_texts()
        self._refresh_current_screen()

    def _set_current_language(self, row: languages_service.LanguageRow | None) -> None:
        session.current_language = row
        # طبق درخواستِ صریح: با تعویضِ زبان، متن‌های ثابتِ اعلام‌شده در KV
        # هم باید زنده ترجمه شوند — چون خودِ session.current_language یک
        # Kivy Property نیست، این پرچمِ کمکی روی App همان نقش را بازی
        # می‌کند (توضیحِ کامل در app.py، PeechaApp.ui_language_code).
        from kivymd.app import MDApp  # noqa: PLC0415

        app = MDApp.get_running_app()
        if app is not None:
            app.ui_language_code = row.code if row else ""

    def _refresh_nav_item_texts(self) -> None:
        # طبق درخواستِ صریح: نوار کناری فقط یک‌بار ساخته می‌شود (برای
        # سرعت)، پس با تعویضِ زبان از هدر باید متنِ آیتم‌ها را دوباره از
        # روی NAV_ITEMS با ترجمه‌ی تازه بازسازی کنیم — خودِ ویجت‌ها را نه.
        from peecha.ui.widgets import PNavItem  # noqa: PLC0415

        for code, label_widget in self._group_labels.items():
            group_item = next(i for i in NAV_ITEMS if i["code"] == code)
            label_widget.text = shape(tr(group_item["label"]))

        clickable_widgets = [w for w in self.ids.nav_list.children[::-1] if isinstance(w, PNavItem)]
        for widget, item in zip(clickable_widgets, _flatten_nav_items(), strict=True):
            widget.text = shape(tr(item["label"]))

    def _refresh_current_screen(self) -> None:
        """صفحه‌ی محتوایِ جاری را بعد از تعویضِ شرکت/زبان دوباره از دیتابیس
        بار می‌کند — عمداً on_pre_enter صدا زده نمی‌شود چون آن هم
        bind_shortcuts() را دوباره صدا می‌زند و چون صفحه از قبل باز/بایند
        است، این باعث دوبار-بایندشدنِ میانبرهای کیبورد می‌شود (با تست مستقیم
        پیدا شد)."""
        screen = self.ids.content_manager.current_screen
        if screen is None:
            return
        if hasattr(screen, "apply_field_labels"):
            screen.apply_field_labels()
        if hasattr(screen, "_load_accounts") and hasattr(screen, "cancel_edit"):
            screen._load_accounts()
            screen.cancel_edit()
        elif hasattr(screen, "cancel_edit"):
            screen.cancel_edit()
        elif hasattr(screen, "refresh_list"):
            screen.refresh_list()
        elif hasattr(screen, "refresh"):
            screen.refresh()

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
