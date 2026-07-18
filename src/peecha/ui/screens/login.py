"""صفحه‌ی ورود — پوسته‌ی اولیه، بدون اتصال واقعی به sec.users هنوز.

TODO: اتصال به سرویس احراز هویت (بررسی password_hash/password_salt در
sec.users، انتخاب شرکت پیش‌فرض از sec.user_companies) در قدم بعدی.
"""

from __future__ import annotations

import os

from kivy.lang import Builder
from kivymd.uix.screen import MDScreen

from peecha.ui.rtl import shape

_KV_PATH = os.path.join(os.path.dirname(__file__), "login.kv")
Builder.load_file(_KV_PATH)


class LoginScreen(MDScreen):
    def attempt_login(self) -> None:
        username_field = self.ids.username_field
        # password_field محفوظ برای اتصال به سرویس احراز هویت در قدم بعدی
        # TODO: جایگزینی با فراخوانی واقعی سرویس احراز هویت (sec.users)
        message = (
            f"ورود کاربر «{username_field.text}» هنوز پیاده نشده — این فقط پوسته‌ی UI است."
            if username_field.text
            else "نام کاربری را وارد کنید."
        )
        self.ids.status_label.text = shape(message)

    def open_connection_settings(self) -> None:
        self.manager.current = "connection_settings"
