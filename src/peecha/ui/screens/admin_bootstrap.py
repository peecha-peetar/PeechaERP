"""راه‌اندازی اولیه‌ی سیستم — فقط وقتی sec.users خالی است نمایش داده می‌شود
(از login.py صدا زده می‌شود). اولین کاربر مدیر + اولین شرکت را یک‌جا می‌سازد."""

from __future__ import annotations

import os

from kivy.lang import Builder
from kivymd.uix.screen import MDScreen
from sqlalchemy import select

from peecha import session
from peecha.db.base import new_session
from peecha.db.models.security import UserCompany
from peecha.services.bootstrap import bootstrap_system
from peecha.ui.rtl import shape
from peecha.ui.shortcuts import KeyboardShortcutMixin

_KV_PATH = os.path.join(os.path.dirname(__file__), "admin_bootstrap.kv")
Builder.load_file(_KV_PATH)


class AdminBootstrapScreen(KeyboardShortcutMixin, MDScreen):
    def on_pre_enter(self, *args):
        self.ids.status_label.text = ""
        self.bind_shortcuts()
        self.ids.company_name_field.focus = True

    def on_leave(self, *args):
        self.unbind_shortcuts()

    def on_shortcut_save(self) -> None:
        self.create_admin()

    def _set_status(self, message: str) -> None:
        self.ids.status_label.text = shape(message)

    def create_admin(self) -> None:
        username = self.ids.username_field.text.strip()
        full_name = self.ids.full_name_field.text.strip()
        company_name = self.ids.company_name_field.text.strip()
        password = self.ids.password_field.text
        confirm = self.ids.confirm_password_field.text

        if not username or not full_name or not company_name:
            self._set_status("همه‌ی فیلدها را پر کنید.")
            return
        if len(password) < 6:
            self._set_status("رمز عبور باید حداقل ۶ کاراکتر باشد.")
            return
        if password != confirm:
            self._set_status("تکرار رمز عبور مطابقت ندارد.")
            return

        try:
            user = bootstrap_system(username, full_name, password, company_name)
        except Exception as exc:  # noqa: BLE001 - نمایش هر خطای دیتابیس به کاربر
            self._set_status(f"خطا در راه‌اندازی: {exc}")
            return

        session.current_user = user
        with new_session() as db_session:
            user_company = db_session.scalar(select(UserCompany).where(UserCompany.user_id == user.user_id))
            from peecha.db.models.core import Company  # noqa: PLC0415

            session.current_company = db_session.get(Company, user_company.company_id) if user_company else None

        self.manager.current = "shell"
