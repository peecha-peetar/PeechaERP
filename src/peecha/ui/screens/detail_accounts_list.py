"""صفحه‌ی فهرستِ واحدِ همه‌ی «تفصیلی‌ها» — طبقِ درخواستِ صریح: تفصیلی
(مشتری/تامین‌کننده/پرسنل/بانک/صندوق‌وتنخواه/دارایی‌ثابت/کالا/...)، مرکزِ
هزینه و پروژه همگی مفهوماً «گروهِ تفصیلی»‌اند و باید در یک فهرستِ واحد،
با ستونِ نوعِ تفصیلی و ستونِ سطح، دیده شوند. کلیک روی هر ردیف، بسته به
نوعِ گروهش، فرمِ درست را باز می‌کند (مشتری/تامین‌کننده/پرسنل → صفحه‌ی
اختصاصیِ خودشان؛ بقیه → صفحه‌ی مدیریتِ ابعادِ تفصیلی، با انتخابِ خودکارِ
گروه و بازکردنِ فرمِ ویرایش)."""

from __future__ import annotations

import os

from kivy.factory import Factory
from kivy.lang import Builder
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, ObjectProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.screen import MDScreen

from peecha import session
from peecha.services import detail_dimensions as dimensions_service
from peecha.ui import theme
from peecha.ui.i18n import tr
from peecha.ui.rtl import shape

_KV_PATH = os.path.join(os.path.dirname(__file__), "detail_accounts_list.kv")
Builder.load_file(_KV_PATH)

_GROUP_SCREEN_BY_PERSON_CODE = {
    "CUSTOMER": "GL_CUSTOMERS",
    "SUPPLIER": "GL_SUPPLIERS",
    "PERSONNEL": "GL_PERSONNEL",
}


class DetailAccountUnifiedRowWidget(RecycleDataViewBehavior, ButtonBehavior, MDBoxLayout):
    detail_account_id = NumericProperty(0)
    dimension_type_id = NumericProperty(0)
    person_group_code = StringProperty("")
    group_text = StringProperty("")
    level_text = StringProperty("")
    code_text = StringProperty("")
    name_text = StringProperty("")
    status_text = StringProperty("")
    status_badge_color = ListProperty([0, 0, 0, 1])
    zebra = BooleanProperty(False)
    on_open = ObjectProperty(None)

    def on_release(self) -> None:
        if self.on_open is not None:
            self.on_open(self.dimension_type_id, self.detail_account_id, self.person_group_code or None)


Factory.register("DetailAccountUnifiedRowWidget", cls=DetailAccountUnifiedRowWidget)


class DetailAccountsListScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._entries: list[dimensions_service.UnifiedDetailAccountRow] = []

    def on_pre_enter(self, *args):
        self.refresh_list()

    def _current_company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def refresh_list(self) -> None:
        company_id = self._current_company_id()
        self._entries = dimensions_service.list_all_detail_accounts(company_id) if company_id is not None else []
        self._apply_filter()

    def filter_entries(self) -> None:
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self.ids.search_field.text.strip()
        if not query:
            filtered = self._entries
        else:
            filtered = [
                e
                for e in self._entries
                if query in e.group_name
                or query in e.full_code
                or (e.name and query in e.name)
            ]

        self.ids.status_label.text = (
            "" if not self._entries else shape(tr("{} ردیف").format(len(filtered)))
        )

        if not filtered:
            self.ids.entries_list.data = [
                {
                    "viewclass": "PEmptyState",
                    "icon": "shape-outline",
                    "text": shape(tr("تفصیلی‌ای یافت نشد.") if self._entries else tr("هنوز هیچ تفصیلی‌ای تعریف نشده است.")),
                }
            ]
            return

        self.ids.entries_list.data = [
            {
                "detail_account_id": e.detail_account_id,
                "dimension_type_id": e.dimension_type_id,
                "person_group_code": e.person_group_code or "",
                "on_open": self.open_entry,
                "group_text": shape(e.group_name),
                "level_text": str(e.level_no),
                "code_text": e.full_code,
                "name_text": shape(e.name or "—"),
                "status_text": shape(tr("فعال") if e.is_active else tr("غیرفعال")),
                "status_badge_color": theme.SUCCESS if e.is_active else theme.TEXT_DISABLED,
                "zebra": i % 2 == 1,
            }
            for i, e in enumerate(filtered)
        ]

    def open_entry(self, dimension_type_id: int, detail_account_id: int, person_group_code: str | None) -> None:
        from kivymd.app import MDApp  # noqa: PLC0415

        shell = MDApp.get_running_app().root.get_screen("shell")
        target_code = _GROUP_SCREEN_BY_PERSON_CODE.get(person_group_code or "")
        if target_code is not None:
            shell.open_screen(target_code, then=lambda screen: screen.edit_person(detail_account_id))
        else:
            shell.open_screen(
                "GL_DIM",
                then=lambda screen: screen.select_type_and_edit(dimension_type_id, detail_account_id),
            )
