"""صفحه‌ی ورود — احراز هویت واقعی در برابر sec.users."""

from __future__ import annotations

import os

from kivy.lang import Builder
from kivymd.uix.screen import MDScreen
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from peecha import session
from peecha.db.base import new_session
from peecha.db.models.security import UserCompany
from peecha.services.auth import authenticate, has_any_user
from peecha.ui.rtl import shape
from peecha.ui.shortcuts import KeyboardShortcutMixin

_KV_PATH = os.path.join(os.path.dirname(__file__), "login.kv")
Builder.load_file(_KV_PATH)


class LoginScreen(KeyboardShortcutMixin, MDScreen):
    def on_pre_enter(self, *args):
        self.ids.status_label.text = ""
        self.ids.bootstrap_button.size_hint_y = None
        self.bind_shortcuts()
        # فوکوس خودکار روی اولین فیلد: کاربر بدون لمس ماوس هم بتواند تایپ را شروع کند
        self.ids.username_field.focus = True
        try:
            no_users = not has_any_user()
        except SQLAlchemyError:
            self.ids.bootstrap_button.opacity = 0
            self.ids.bootstrap_button.disabled = True
            self.ids.bootstrap_button.height = "0dp"
            self._set_status("اتصال به دیتابیس برقرار نشد — از «تنظیمات اتصال به دیتابیس» بررسی کنید.")
            return
        self.ids.bootstrap_button.opacity = 1 if no_users else 0
        self.ids.bootstrap_button.disabled = not no_users
        self.ids.bootstrap_button.height = "36dp" if no_users else "0dp"
        if no_users:
            self._set_status("هنوز کاربری ثبت نشده — از دکمه‌ی زیر شروع کنید.")

    def on_leave(self, *args):
        self.unbind_shortcuts()

    def on_shortcut_save(self) -> None:
        self.attempt_login()

    def _set_status(self, message: str) -> None:
        self.ids.status_label.text = shape(message)

    def attempt_login(self) -> None:
        username = self.ids.username_field.text.strip()
        password = self.ids.password_field.text

        if not username or not password:
            self._set_status("نام کاربری و رمز عبور را وارد کنید.")
            return

        try:
            user = authenticate(username, password)
        except SQLAlchemyError:
            self._set_status("اتصال به دیتابیس برقرار نشد.")
            return
        if user is None:
            self._set_status("نام کاربری یا رمز عبور نادرست است.")
            return

        session.current_user = user
        with new_session() as db_session:
            user_company = db_session.scalar(
                select(UserCompany)
                .where(UserCompany.user_id == user.user_id)
                .order_by(UserCompany.is_default.desc())
            )
        if user_company is not None:
            from peecha.db.models.core import Company  # noqa: PLC0415

            with new_session() as db_session:
                session.current_company = db_session.get(Company, user_company.company_id)
        else:
            session.current_company = None

        self.manager.current = "shell"

    def open_connection_settings(self) -> None:
        self.manager.current = "connection_settings"

    def open_admin_bootstrap(self) -> None:
        self.manager.current = "admin_bootstrap"
