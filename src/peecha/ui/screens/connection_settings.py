"""فرم تنظیمات اتصال به دیتابیس — جایگزین ویرایش دستی .env برای کاربر نهایی.

اولین بار که برنامه اجرا می‌شود (وقتی هنوز هیچ تنظیماتی ذخیره نشده) همین
صفحه باز می‌شود؛ بعد از آن، از صفحه‌ی ورود هم قابل‌دسترسی است.
"""

from __future__ import annotations

import os

from kivy.lang import Builder
from kivymd.uix.screen import MDScreen

from peecha.config import DatabaseConfig, load_database_config, save_database_config, test_connection
from peecha.db.base import reset_engine
from peecha.ui.rtl import shape
from peecha.ui.theme import SEMANTIC_COLORS

_KV_PATH = os.path.join(os.path.dirname(__file__), "connection_settings.kv")
Builder.load_file(_KV_PATH)


class ConnectionSettingsScreen(MDScreen):
    def on_pre_enter(self, *args):
        config = load_database_config()
        self.ids.host_field.text = config.host
        self.ids.port_field.text = str(config.port)
        self.ids.name_field.text = config.name
        self.ids.user_field.text = config.user
        self.ids.password_field.text = config.password
        self.ids.status_label.text = ""

    def _current_config(self) -> DatabaseConfig:
        return DatabaseConfig(
            host=self.ids.host_field.text.strip(),
            port=int(self.ids.port_field.text.strip() or 5432),
            name=self.ids.name_field.text.strip(),
            user=self.ids.user_field.text.strip(),
            password=self.ids.password_field.text,
        )

    def _set_status(self, message: str, ok: bool) -> None:
        label = self.ids.status_label
        label.text = shape(message)
        label.theme_text_color = "Custom"
        label.text_color = SEMANTIC_COLORS["light"]["success" if ok else "danger"]

    def test_connection_pressed(self) -> None:
        self._set_status("در حال بررسی اتصال...", ok=True)
        ok, message = test_connection(self._current_config())
        self._set_status(("اتصال موفق بود." if ok else f"اتصال ناموفق: {message}"), ok=ok)

    def save_and_continue(self) -> None:
        try:
            config = self._current_config()
        except ValueError:
            self._set_status("پورت باید یک عدد باشد.", ok=False)
            return
        save_database_config(config)
        reset_engine()
        self.manager.current = "login"
