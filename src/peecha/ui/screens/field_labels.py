"""صفحه‌ی «عنوان فیلدها» — مدیریتِ عنوانِ فیلدهای فرم‌ها به‌تفکیکِ زبان.

یک فرم + یک زبان انتخاب می‌شود، بعد فهرستِ فیلدهای همان فرم با عنوانِ
پیش‌فرض (فارسیِ هاردکدشده در کد) و عنوانِ قابل‌ویرایش برای همان زبان نشان
داده می‌شود. اگر برای زبانی هنوز چیزی ثبت نشده، عنوانِ پیش‌فرض نمایش داده
می‌شود (نه خالی) — دقیقاً طبق درخواستِ صریح."""

from __future__ import annotations

import os

from kivy.lang import Builder
from kivy.properties import StringProperty
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen

from peecha import session
from peecha.services import field_labels as field_labels_service
from peecha.services import languages as languages_service
from peecha.services import roles as roles_service
from peecha.ui.i18n import tr
from peecha.ui.rtl import shape
from peecha.ui.shortcuts import KeyboardShortcutMixin

_KV_PATH = os.path.join(os.path.dirname(__file__), "field_labels.kv")
Builder.load_file(_KV_PATH)

# فقط فرم‌هایی که فیلدِ قابل‌ترجمه دارند (نه صفحاتِ پیش از ورود — چون
# سوییچرِ زبان فقط بعد از ورود در هدر در دسترس است و آن صفحات هنوز
# «زبانِ فعال»ی ندارند).
_MANAGED_FORMS = [
    "chart_of_accounts",
    "journal_entry",
    "languages",
    "companies",
    "fiscal_years",
    "users",
    "roles",
]


class _FieldEditRow(MDBoxLayout):
    default_label_text = StringProperty("")

    def __init__(self, field_id: int, current_label: str, has_override: bool, on_save, on_reset, **kwargs):
        super().__init__(**kwargs)
        self.field_id = field_id
        self._on_save = on_save
        self._on_reset = on_reset
        self.ids.value_field.set_value(current_label)
        self.ids.reset_button.disabled = not has_override
        self.ids.reset_button.opacity = 1 if has_override else 0.35

    def save(self) -> None:
        self._on_save(self.field_id, self.ids.value_field.value)

    def reset(self) -> None:
        self._on_reset(self.field_id)


class FieldLabelsScreen(KeyboardShortcutMixin, MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._form_code = _MANAGED_FORMS[0]
        self._language_options: list[languages_service.LanguageRow] = []
        self._language_id: int | None = None
        self._menu: MDDropdownMenu | None = None

    def on_pre_enter(self, *args):
        self._language_options = languages_service.list_languages()
        if self._language_id is None or not any(l.language_id == self._language_id for l in self._language_options):
            preferred = session.current_language.language_id if session.current_language else None
            chosen = next((l for l in self._language_options if l.language_id == preferred), None)
            chosen = chosen or next((l for l in self._language_options if l.is_default), None)
            chosen = chosen or (self._language_options[0] if self._language_options else None)
            self._language_id = chosen.language_id if chosen else None
        self._refresh_form_text()
        self._refresh_language_text()
        self.refresh_list()
        self.bind_shortcuts()

    def on_leave(self, *args):
        self.unbind_shortcuts()

    def _set_status(self, message: str) -> None:
        self.ids.status_label.text = shape(message)

    def _refresh_form_text(self) -> None:
        label = roles_service.FORM_LABELS.get(self._form_code, self._form_code)
        self.ids.form_button.text = shape(tr(label))

    def open_form_menu(self) -> None:
        from peecha.ui.widgets import open_rtl_dropdown  # noqa: PLC0415

        items = [
            {
                "text": shape(tr(roles_service.FORM_LABELS.get(code, code))),
                "on_release": lambda c=code: (self._menu.dismiss(), self._select_form(c)),
            }
            for code in _MANAGED_FORMS
        ]
        self._menu = open_rtl_dropdown(self.ids.form_button, items, width_mult=3)

    def _select_form(self, form_code: str) -> None:
        self._form_code = form_code
        self._refresh_form_text()
        self.refresh_list()

    def _refresh_language_text(self) -> None:
        row = next((l for l in self._language_options if l.language_id == self._language_id), None)
        self.ids.language_button.text = shape(row.native_name if row else tr("— زبانی تعریف نشده —"))

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
        self._language_id = language_id
        self._refresh_language_text()
        self.refresh_list()

    def refresh_list(self) -> None:
        self.ids.fields_list.clear_widgets()
        if self._language_id is None:
            self._set_status(tr("ابتدا یک زبان تعریف کنید."))
            return
        self._set_status(tr(""))

        from peecha.ui.widgets import PEmptyState  # noqa: PLC0415

        rows = field_labels_service.list_fields(self._form_code, self._language_id)
        if not rows:
            self.ids.fields_list.add_widget(
                PEmptyState(icon="form-textbox", text=shape(tr("این فرم فیلدی برای مدیریتِ عنوان ندارد.")))
            )
        for row in rows:
            self.ids.fields_list.add_widget(
                _FieldEditRow(
                    field_id=row.field_id,
                    current_label=row.label or row.default_label,
                    has_override=row.label is not None,
                    on_save=self._save_label,
                    on_reset=self._reset_label,
                    default_label_text=shape(tr("پیش‌فرض: {}").format(row.default_label)),
                )
            )

    def _save_label(self, field_id: int, label: str) -> None:
        field_labels_service.set_label(field_id, self._language_id, label)
        self._set_status(tr("ذخیره شد."))
        self.refresh_list()

    def _reset_label(self, field_id: int) -> None:
        field_labels_service.set_label(field_id, self._language_id, None)
        self._set_status(tr("به عنوانِ پیش‌فرض بازگشت."))
        self.refresh_list()
