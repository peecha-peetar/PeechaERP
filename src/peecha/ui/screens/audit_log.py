"""صفحه‌ی ردِ حسابرسی — فهرستِ فقط‌خواندنیِ رویدادهای مهمِ کسب‌وکاری (ایجاد/
ویرایش/حذفِ حساب‌های کدینگ و اسنادِ حسابداری، فعلاً)؛ چون خودِ جدول
audit.activity_log در دیتابیس با تریگر از UPDATE/DELETE محافظت می‌شود
(006_audit_log.sql)، این صفحه هم عمداً هیچ فرمِ افزودن/ویرایشی ندارد —
فقط نمایش و فیلتر."""

from __future__ import annotations

import json
import os

from kivy.factory import Factory
from kivy.lang import Builder
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, ObjectProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen

from peecha import session
from peecha.services import audit as audit_service
from peecha.ui import numerals, theme
from peecha.ui.i18n import tr
from peecha.ui.rtl import shape
from peecha.ui.shortcuts import KeyboardShortcutMixin

_KV_PATH = os.path.join(os.path.dirname(__file__), "audit_log.kv")
Builder.load_file(_KV_PATH)

_ACTION_LABELS = {"CREATE": "ایجاد", "UPDATE": "ویرایش", "DELETE": "حذف"}
_ACTION_COLORS = {"CREATE": theme.SUCCESS, "UPDATE": theme.INFO, "DELETE": theme.DANGER}
_ALL_TYPES_LABEL = "همه‌ی انواع"


class AuditLogRowWidget(RecycleDataViewBehavior, ButtonBehavior, MDBoxLayout):
    log_id = NumericProperty(0)
    date_text = StringProperty("")
    user_text = StringProperty("")
    entity_text = StringProperty("")
    entity_id_text = StringProperty("")
    action_text = StringProperty("")
    action_badge_color = ListProperty([0, 0, 0, 1])
    zebra = BooleanProperty(False)
    on_show = ObjectProperty(None)

    def on_release(self) -> None:
        if self.on_show is not None:
            self.on_show(self.log_id)


Factory.register("AuditLogRowWidget", cls=AuditLogRowWidget)


class AuditLogScreen(KeyboardShortcutMixin, MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._entity_type: str | None = None
        self._entity_types: list[str] = []
        self._rows_by_id: dict[int, audit_service.ActivityLogRow] = {}
        self._menu: MDDropdownMenu | None = None
        self._detail_dialog: MDDialog | None = None

    def on_pre_enter(self, *args):
        self._entity_types = audit_service.list_entity_types()
        self._set_type_text()
        self.refresh_list()
        self.bind_shortcuts()

    def on_leave(self, *args):
        self.unbind_shortcuts()

    def _current_company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def _set_status(self, message: str) -> None:
        self.ids.status_label.text = shape(message)

    def _set_type_text(self) -> None:
        self.ids.type_button.text = shape(tr(self._entity_type) if self._entity_type else tr(_ALL_TYPES_LABEL))

    def open_type_menu(self) -> None:
        from peecha.ui.widgets import open_rtl_dropdown  # noqa: PLC0415

        items = [
            {"text": shape(tr(_ALL_TYPES_LABEL)), "on_release": lambda: (self._menu.dismiss(), self._select_type(None))}
        ]
        for entity_type in self._entity_types:
            items.append(
                {
                    "text": shape(entity_type),
                    "on_release": lambda value=entity_type: (self._menu.dismiss(), self._select_type(value)),
                }
            )
        self._menu = open_rtl_dropdown(self.ids.type_button, items, width_mult=3)

    def _select_type(self, entity_type: str | None) -> None:
        self._entity_type = entity_type
        self._set_type_text()
        self.refresh_list()

    def refresh_list(self) -> None:
        rows = audit_service.list_activity_log(company_id=self._current_company_id(), entity_type=self._entity_type)
        self._rows_by_id = {r.log_id: r for r in rows}
        self._set_status(tr("{} رویداد یافت شد.").format(numerals.to_persian_digits(str(len(rows)))))

        if not rows:
            self.ids.log_list.data = [
                {"viewclass": "PEmptyState", "icon": "history", "text": shape(tr("هنوز رویدادی ثبت نشده است."))}
            ]
            return

        self.ids.log_list.data = [
            {
                "log_id": row.log_id,
                "on_show": self.show_details,
                "date_text": numerals.format_jalali_datetime(row.created_at),
                "user_text": shape(row.user_full_name or tr("سیستم")),
                "entity_text": shape(row.entity_type),
                "entity_id_text": numerals.to_persian_digits(str(row.entity_id)),
                "action_text": shape(tr(_ACTION_LABELS.get(row.action, row.action))),
                "action_badge_color": _ACTION_COLORS.get(row.action, theme.TEXT_DISABLED),
                "zebra": i % 2 == 1,
            }
            for i, row in enumerate(rows)
        ]

    def show_details(self, log_id: int) -> None:
        row = self._rows_by_id.get(log_id)
        if row is None:
            return
        if self._detail_dialog is not None:
            self._detail_dialog.dismiss()

        pretty = json.dumps(row.changes, ensure_ascii=False, indent=2)
        action_label = tr(_ACTION_LABELS.get(row.action, row.action))
        title = f"{action_label} — {row.entity_type} #{row.entity_id}"

        self._detail_dialog = MDDialog(
            title=title,
            text=pretty,
            buttons=[MDFlatButton(text=shape(tr("بستن")), on_release=lambda *_: self._detail_dialog.dismiss())],
        )
        self._detail_dialog.open()
