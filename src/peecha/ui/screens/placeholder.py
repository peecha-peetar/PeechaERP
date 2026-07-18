"""صفحه‌ی موقت برای ماژول‌هایی که هنوز ساخته نشده‌اند."""

from __future__ import annotations

import os

from kivy.lang import Builder
from kivy.properties import StringProperty
from kivymd.uix.screen import MDScreen

from peecha.ui.rtl import shape

_KV_PATH = os.path.join(os.path.dirname(__file__), "placeholder.kv")
Builder.load_file(_KV_PATH)


class PlaceholderScreen(MDScreen):
    message = StringProperty("")

    def set_module_name(self, module_name: str) -> None:
        self.message = shape(f"ماژول «{module_name}» به‌زودی اضافه می‌شود.")
