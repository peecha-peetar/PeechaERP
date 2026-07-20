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
from peecha.db.schema_bootstrap import initialize_schema, is_initialized
from peecha.ui.i18n import tr
from peecha.ui.rtl import shape
from peecha.ui.shortcuts import KeyboardShortcutMixin
from peecha.ui.theme import SEMANTIC_COLORS

_KV_PATH = os.path.join(os.path.dirname(__file__), "connection_settings.kv")
Builder.load_file(_KV_PATH)


class ConnectionSettingsScreen(KeyboardShortcutMixin, MDScreen):
    def on_pre_enter(self, *args):
        config = load_database_config()
        self.ids.host_field.text = config.host
        self.ids.port_field.text = str(config.port)
        self.ids.name_field.text = config.name
        self.ids.user_field.text = config.user
        self.ids.password_field.text = config.password
        self.ids.status_label.text = ""
        self.bind_shortcuts()
        self.ids.host_field.focus = True

    def on_leave(self, *args):
        self.unbind_shortcuts()

    def on_shortcut_save(self) -> None:
        self.save_and_continue()

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
        self._set_status(tr("در حال بررسی اتصال..."), ok=True)
        ok, message = test_connection(self._current_config())
        self._set_status(("اتصال موفق بود." if ok else f"اتصال ناموفق: {message}"), ok=ok)

    def create_tables_pressed(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.exc import SQLAlchemyError

        self._set_status(tr("در حال بررسی/ساخت جدول‌ها..."), ok=True)
        try:
            config = self._current_config()
        except ValueError:
            self._set_status(tr("پورت باید یک عدد باشد."), ok=False)
            return

        engine = create_engine(config.sqlalchemy_url, future=True)
        try:
            if is_initialized(engine):
                self._set_status(tr("جدول‌ها از قبل ساخته شده‌اند؛ کاری لازم نبود."), ok=True)
                return
            initialize_schema(engine)
            self._set_status(tr("جدول‌های دیتابیس با موفقیت ساخته شدند."), ok=True)
        except SQLAlchemyError as exc:
            self._set_status(f"ساخت جدول‌ها ناموفق بود: {exc.__cause__ or exc}", ok=False)
        finally:
            engine.dispose()

    def save_and_continue(self) -> None:
        try:
            config = self._current_config()
        except ValueError:
            self._set_status(tr("پورت باید یک عدد باشد."), ok=False)
            return
        save_database_config(config)
        reset_engine()
        self.manager.current = "login"
