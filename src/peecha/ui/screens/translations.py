"""صفحه‌ی «ترجمه‌ها» — فرمِ مدیریتِ فایلِ ترجمه‌ی هر زبان (طبق درخواستِ صریح:
«فایل هم بصورت فرمی باشه که کاربر بتونه دسترسی داشته باشه تا اصلاحش کنه»).

هر ردیف یک متنِ منبعِ فارسی (فقط‌خواندنی) + فیلدِ ترجمه (قابل‌ویرایش، ذخیره‌ی
فوری) است. دکمه‌ی «ترجمه با سرویسِ آنلاین» فقط مواردی که هنوز ترجمه نشده‌اند
(مقدار = خودِ متنِ فارسی) را با LibreTranslate پر می‌کند — طبق درخواستِ صریح،
فقط با فراخوانیِ صریحِ کاربر، نه خودکار."""

from __future__ import annotations

import os
import threading

from kivy.clock import Clock
from kivy.lang import Builder
from kivy.properties import BooleanProperty, StringProperty
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen

from peecha.services import languages as languages_service
from peecha.services import machine_translation
from peecha.ui import i18n
from peecha.ui.i18n import tr
from peecha.ui.rtl import shape
from peecha.ui.shortcuts import KeyboardShortcutMixin
from peecha.ui.theme import DANGER, TEXT_SECONDARY

_KV_PATH = os.path.join(os.path.dirname(__file__), "translations.kv")
Builder.load_file(_KV_PATH)

_MAX_VISIBLE_ROWS = 300  # جلوگیری از رندرِ بیش‌ازحدِ کند اگر فهرستِ منبع خیلی بزرگ شود


class _TranslationRow(MDBoxLayout):
    source_text = StringProperty("")
    is_untranslated = BooleanProperty(False)

    def __init__(self, source: str, current_value: str, on_save, **kwargs):
        super().__init__(**kwargs)
        self.source = source
        self._on_save = on_save
        self.source_text = shape(source)
        self.is_untranslated = current_value == source
        self.ids.value_field.set_value(current_value)

    def save(self) -> None:
        self._on_save(self.source, self.ids.value_field.value)


class TranslationsScreen(KeyboardShortcutMixin, MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._language_options: list[languages_service.LanguageRow] = []
        self._language_id: int | None = None
        self._filter_text = ""
        self._menu: MDDropdownMenu | None = None
        self._translating = False

    def on_pre_enter(self, *args):
        self._language_options = [row for row in languages_service.list_languages() if not row.is_default]
        if self._language_id is None or not any(l.language_id == self._language_id for l in self._language_options):
            self._language_id = self._language_options[0].language_id if self._language_options else None
        self.ids.service_url_field.text = machine_translation.DEFAULT_BASE_URL
        self._refresh_language_text()
        self.refresh_list()
        self.bind_shortcuts()

    def on_leave(self, *args):
        self.unbind_shortcuts()

    def _set_status(self, message: str, *, is_error: bool = False) -> None:
        self.ids.status_label.text = shape(message)
        self.ids.status_label.text_color = DANGER if is_error else TEXT_SECONDARY

    def _current_language(self) -> languages_service.LanguageRow | None:
        return next((l for l in self._language_options if l.language_id == self._language_id), None)

    def _refresh_language_text(self) -> None:
        row = self._current_language()
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

    def on_filter_text(self, text: str) -> None:
        self._filter_text = text.strip()
        self.refresh_list()

    def refresh_list(self) -> None:
        self.ids.rows_list.clear_widgets()
        language = self._current_language()
        if language is None:
            self._set_status(tr("ابتدا یک زبانِ غیرِپیش‌فرض تعریف کنید."))
            self.ids.translate_online_button.disabled = True
            return
        self.ids.translate_online_button.disabled = self._translating

        from peecha.ui.widgets import PEmptyState  # noqa: PLC0415

        catalog = i18n.get_catalog(language.code)
        sources = i18n.list_source_strings()
        if self._filter_text:
            sources = [
                s for s in sources if self._filter_text in s or self._filter_text in catalog.get(s, s)
            ]
        untranslated_count = sum(1 for s in i18n.list_source_strings() if catalog.get(s, s) == s)
        if not self._translating:
            self._set_status(tr("{} مورد بدون ترجمه از {} مورد.").format(untranslated_count, len(catalog)))

        if not sources:
            self.ids.rows_list.add_widget(
                PEmptyState(icon="translate", text=shape(tr("موردی با این فیلتر پیدا نشد.")))
            )
            return
        for source in sources[:_MAX_VISIBLE_ROWS]:
            self.ids.rows_list.add_widget(
                _TranslationRow(source=source, current_value=catalog.get(source, source), on_save=self._save_translation)
            )

    def _save_translation(self, source: str, value: str) -> None:
        language = self._current_language()
        if language is None:
            return
        i18n.set_translation(language.code, source, value)
        i18n.invalidate_cache(language.code)
        self._set_status(tr("ذخیره شد."))
        self.refresh_list()

    def translate_online(self) -> None:
        language = self._current_language()
        if language is None or self._translating:
            return
        catalog = i18n.get_catalog(language.code)
        untranslated = [s for s in i18n.list_source_strings() if catalog.get(s, s) == s]
        if not untranslated:
            self._set_status(tr("همه‌ی موارد قبلاً ترجمه شده‌اند."))
            return

        base_url = self.ids.service_url_field.text.strip() or machine_translation.DEFAULT_BASE_URL
        target_code = machine_translation.target_language_code(language.code)
        language_id = language.language_id
        language_code = language.code

        self._translating = True
        self.ids.translate_online_button.disabled = True
        self._set_status(tr("در حالِ ترجمه‌ی {} مورد با سرویسِ آنلاین...").format(len(untranslated)))

        def worker() -> None:
            error_message: str | None = None
            result = None
            try:
                result = machine_translation.translate_texts(untranslated, target_code, base_url=base_url)
            except machine_translation.TranslationServiceError as exc:
                error_message = str(exc)
            Clock.schedule_once(lambda _dt: self._on_translate_done(language_id, language_code, result, error_message))

        threading.Thread(target=worker, daemon=True).start()

    def _on_translate_done(
        self,
        language_id: int,
        language_code: str,
        result: machine_translation.TranslationBatchResult | None,
        error_message: str | None,
    ) -> None:
        self._translating = False
        self.ids.translate_online_button.disabled = False
        if error_message:
            self._set_status(tr("خطا: {}").format(error_message), is_error=True)
            return
        i18n.update_catalog(language_code, result.translated)
        i18n.invalidate_cache(language_code)
        message = tr("{} مورد ترجمه شد.").format(len(result.translated))
        if result.failed_texts:
            message += " " + tr("({} مورد ناموفق بود.)").format(len(result.failed_texts))
        self._set_status(message)
        if self._language_id == language_id:
            self.refresh_list()
