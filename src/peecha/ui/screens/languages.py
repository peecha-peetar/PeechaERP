"""صفحه‌ی مدیریت زبان‌ها — تعریفِ زبان‌های قابل‌استفاده در کل سیستم
(core.languages)، پایه‌ی چندزبانگی برای شرکت‌ها/کاربران/ترجمه‌ها."""

from __future__ import annotations

import os

from kivy.lang import Builder
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.screen import MDScreen

from peecha import session
from peecha.services import field_labels as field_labels_service
from peecha.services import languages as languages_service
from peecha.ui import theme
from peecha.ui.i18n import tr
from peecha.ui.rtl import shape
from peecha.ui.shortcuts import KeyboardShortcutMixin

_KV_PATH = os.path.join(os.path.dirname(__file__), "languages.kv")
Builder.load_file(_KV_PATH)


class LanguageRowWidget(ButtonBehavior, MDBoxLayout):
    code_text = StringProperty("")
    name_text = StringProperty("")
    direction_text = StringProperty("")
    default_text = StringProperty("")
    status_text = StringProperty("")
    is_active_row = BooleanProperty(True)
    zebra = BooleanProperty(False)
    selected = BooleanProperty(False)

    def __init__(self, language_id: int, on_edit, on_delete, **kwargs):
        super().__init__(**kwargs)
        self.language_id = language_id
        self._on_edit = on_edit
        self._on_delete = on_delete

    def on_release(self) -> None:
        self._on_edit(self.language_id)

    def request_delete(self) -> None:
        self._on_delete(self.language_id)


class LanguagesScreen(KeyboardShortcutMixin, MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._rows_by_id: dict[int, languages_service.LanguageRow] = {}
        self._editing_language_id: int | None = None
        self._delete_dialog: MDDialog | None = None

    def on_pre_enter(self, *args):
        self.apply_field_labels()
        self.refresh_list()
        self.bind_shortcuts()

    def on_leave(self, *args):
        self.unbind_shortcuts()

    def apply_field_labels(self) -> None:
        language_id = session.current_language.language_id if session.current_language else None
        labels = {k: tr(v) for k, v in field_labels_service.get_labels_map("languages", language_id).items()}
        self.ids.code_field.hint_text = shape(labels["code"])
        self.ids.name_field.hint_text = shape(labels["native_name"])
        self.ids.sort_order_field.hint_text = shape(labels["sort_order"])

    def on_shortcut_save(self) -> None:
        self.save_language()

    def on_shortcut_cancel(self) -> bool:
        if self._editing_language_id is not None:
            self.cancel_edit()
            return True
        return False

    def on_shortcut_delete(self) -> bool:
        if self._editing_language_id is not None:
            self.confirm_delete(self._editing_language_id)
            return True
        return False

    def _set_status(self, message: str) -> None:
        self.ids.status_label.text = shape(message)

    def refresh_list(self) -> None:
        self.ids.languages_list.clear_widgets()
        from peecha.ui.widgets import PEmptyState  # noqa: PLC0415

        rows = languages_service.list_languages()
        self._rows_by_id = {r.language_id: r for r in rows}
        self.ids.grid_header.opacity = 1 if rows else 0
        if not rows:
            self.ids.languages_list.add_widget(
                PEmptyState(icon="translate", text=shape(tr("هنوز زبانی تعریف نشده است.")))
            )
        for i, row in enumerate(rows):
            self.ids.languages_list.add_widget(
                LanguageRowWidget(
                    language_id=row.language_id,
                    on_edit=self.edit_language,
                    on_delete=self.confirm_delete,
                    code_text=row.code,
                    name_text=shape(row.native_name),
                    direction_text=shape(tr("راست‌به‌چپ") if row.is_rtl else tr("چپ‌به‌راست")),
                    default_text=shape(tr("پیش‌فرض") if row.is_default else ""),
                    status_text=shape(tr("فعال") if row.is_active else tr("غیرفعال")),
                    is_active_row=row.is_active,
                    zebra=i % 2 == 1,
                    selected=row.language_id == self._editing_language_id,
                )
            )
        if self._editing_language_id is not None and self._editing_language_id not in self._rows_by_id:
            self.cancel_edit()

    def edit_language(self, language_id: int) -> None:
        row = self._rows_by_id.get(language_id)
        if row is None:
            return
        self._editing_language_id = language_id
        self.ids.code_field.set_value(row.code)
        self.ids.code_field.disabled = True
        self.ids.name_field.set_value(row.native_name)
        self.ids.name_field.focus = True
        self.ids.sort_order_field.text = str(row.sort_order)
        self.ids.is_rtl_checkbox.active = row.is_rtl
        self.ids.is_default_checkbox.active = row.is_default
        self.ids.is_active_checkbox.active = row.is_active
        self.ids.form_title.text = shape(tr("ویرایش زبان «{}»").format(row.native_name))
        self.ids.save_button.text = shape(tr("ذخیره تغییرات"))
        self.ids.cancel_edit_button.opacity = 1
        self.ids.cancel_edit_button.disabled = False
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "36dp"
        self._set_status(tr("در حال ویرایش «{}» — Escape برای لغو.").format(row.native_name))
        self.refresh_list()

    def cancel_edit(self) -> None:
        self._editing_language_id = None
        self.ids.code_field.text = ""
        self.ids.code_field.disabled = False
        self.ids.name_field.text = ""
        self.ids.sort_order_field.text = ""
        self.ids.is_rtl_checkbox.active = False
        self.ids.is_default_checkbox.active = False
        self.ids.is_active_checkbox.active = True
        self.ids.form_title.text = shape(tr("افزودن زبان جدید"))
        self.ids.save_button.text = shape(tr("افزودن زبان"))
        self.ids.cancel_edit_button.opacity = 0
        self.ids.cancel_edit_button.disabled = True
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "0dp"
        self._set_status("")
        self.refresh_list()

    def save_language(self) -> None:
        from peecha.ui import numerals  # noqa: PLC0415

        name = self.ids.name_field.value.strip()
        sort_order_text = numerals.to_ascii_digits(self.ids.sort_order_field.text.strip())
        sort_order = int(sort_order_text) if sort_order_text.isdigit() else 0

        if self._editing_language_id is not None:
            if not name:
                self._set_status("نام زبان را وارد کنید.")
                return
            try:
                languages_service.update_language(
                    language_id=self._editing_language_id,
                    native_name=name,
                    is_rtl=self.ids.is_rtl_checkbox.active,
                    is_default=self.ids.is_default_checkbox.active,
                    is_active=self.ids.is_active_checkbox.active,
                    sort_order=sort_order,
                )
            except Exception as exc:  # noqa: BLE001
                self._set_status(tr("خطا: {}").format(exc))
                return
            self.cancel_edit()
            return

        code = self.ids.code_field.value.strip()
        if not code or not name:
            self._set_status("کد و نام زبان را وارد کنید.")
            return
        try:
            languages_service.create_language(
                code=code,
                native_name=name,
                is_rtl=self.ids.is_rtl_checkbox.active,
                is_default=self.ids.is_default_checkbox.active,
                sort_order=sort_order,
            )
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc))
            return

        # طبق درخواستِ صریح: به‌محضِ ساختِ زبانِ تازه، خودکار ترجمه شود و
        # در فایلِ جداگانه‌ی همان زبان ذخیره شود (نه فقط دیتابیس) تا بعداً
        # با ویرایشِ همان فایل قابل‌اصلاح باشد.
        from peecha.services import i18n_translations as i18n_translations_service  # noqa: PLC0415

        i18n_translations_service.generate_translation_file(code)

        self.ids.code_field.text = ""
        self.ids.name_field.text = ""
        self.ids.sort_order_field.text = ""
        self.ids.is_rtl_checkbox.active = False
        self.ids.is_default_checkbox.active = False
        self.refresh_list()

    def confirm_delete(self, language_id: int) -> None:
        row = self._rows_by_id.get(language_id)
        if row is None:
            return

        if self._delete_dialog is not None:
            self._delete_dialog.dismiss()

        def _do_delete(*_args) -> None:
            self._delete_dialog.dismiss()
            self._perform_delete(language_id)

        self._delete_dialog = MDDialog(
            title=shape(tr("حذف زبان")),
            text=shape(tr("زبان «{}» حذف شود؟ این کار قابل بازگشت نیست.").format(row.native_name)),
            buttons=[
                MDFlatButton(text=shape(tr("لغو")), on_release=lambda *_: self._delete_dialog.dismiss()),
                MDRaisedButton(text=shape(tr("حذف")), md_bg_color=theme.DANGER, on_release=_do_delete),
            ],
        )
        self._delete_dialog.open()

    def _perform_delete(self, language_id: int) -> None:
        try:
            languages_service.delete_language(language_id)
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc))
            return
        if self._editing_language_id == language_id:
            self.cancel_edit()
        else:
            self._set_status("زبان حذف شد.")
            self.refresh_list()
