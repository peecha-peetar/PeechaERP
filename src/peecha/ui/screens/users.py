"""صفحه‌ی مدیریت کاربران — تعریفِ کاربر + دسترسیِ او به یک یا چند شرکت
(چندشرکتی). نقش/دسترسیِ ریزتر (منو/فرم/اکشن) در صفحه‌ی «نقش‌ها و دسترسی‌ها»
تعریف می‌شود؛ اینجا فقط سطحِ حساب‌کاربری + کدام شرکت‌ها."""

from __future__ import annotations

import os

from kivy.lang import Builder
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen

from peecha import session
from peecha.services import field_labels as field_labels_service
from peecha.services import users as users_service
from peecha.ui import theme
from peecha.ui.rtl import shape
from peecha.ui.shortcuts import KeyboardShortcutMixin

_KV_PATH = os.path.join(os.path.dirname(__file__), "users.kv")
Builder.load_file(_KV_PATH)


class UserRowWidget(ButtonBehavior, MDBoxLayout):
    username_text = StringProperty("")
    name_text = StringProperty("")
    role_text = StringProperty("")
    status_text = StringProperty("")
    is_active_row = BooleanProperty(True)
    zebra = BooleanProperty(False)
    selected = BooleanProperty(False)

    def __init__(self, user_id: int, on_edit, **kwargs):
        super().__init__(**kwargs)
        self.user_id = user_id
        self._on_edit = on_edit

    def on_release(self) -> None:
        self._on_edit(self.user_id)


class _CompanyCheckRow(MDBoxLayout):
    label_text = StringProperty("")

    def __init__(self, company_id: int, **kwargs):
        super().__init__(**kwargs)
        self.company_id = company_id


class UsersScreen(KeyboardShortcutMixin, MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._rows_by_id: dict[int, users_service.UserRow] = {}
        self._company_options: list[tuple[int, str]] = []
        self._language_options: list[tuple[int, str]] = []
        self._company_checks: list[_CompanyCheckRow] = []
        self._language_id: int | None = None
        self._editing_user_id: int | None = None
        self._menu: MDDropdownMenu | None = None

    def on_pre_enter(self, *args):
        self._company_options = users_service.list_companies_for_picker()
        self._language_options = users_service.list_languages_for_picker()
        if self._language_id is None and self._language_options:
            self._language_id = self._language_options[0][0]
        # طبق درخواستِ صریح: با برگشتن به این صفحه، شرکت‌های تیک‌خورده‌ی
        # فرمِ نیمه‌کاره نباید پاک شود — قبل از بازسازیِ چک‌لیست، انتخابِ
        # فعلی را نگه می‌داریم (اولین بارِ ورود، self._company_checks هنوز
        # خالی است پس چیزی برای نگه‌داشتن نیست).
        previously_checked = set(self._checked_company_ids()) if self._company_checks else None
        self._rebuild_company_checklist(previously_checked)
        self._refresh_language_text()
        self.apply_field_labels()
        self.refresh_list()
        self.bind_shortcuts()

    def on_leave(self, *args):
        self.unbind_shortcuts()

    def apply_field_labels(self) -> None:
        language_id = session.current_language.language_id if session.current_language else None
        labels = field_labels_service.get_labels_map("users", language_id)
        self.ids.username_field.hint_text = shape(labels["username"])
        self.ids.full_name_field.hint_text = shape(labels["full_name"])
        self.ids.email_field.hint_text = shape(labels["email"])
        self.ids.password_field.hint_text = shape(labels["password"])

    def on_shortcut_save(self) -> None:
        self.save_user()

    def on_shortcut_cancel(self) -> bool:
        if self._editing_user_id is not None:
            self.cancel_edit()
            return True
        return False

    def _rebuild_company_checklist(self, checked_ids: set[int] | None = None) -> None:
        checked_ids = checked_ids or set()
        self.ids.companies_checklist_box.clear_widgets()
        self._company_checks = []
        for company_id, display_name in self._company_options:
            row = _CompanyCheckRow(company_id=company_id, label_text=shape(display_name))
            row.ids.check.active = company_id in checked_ids
            self.ids.companies_checklist_box.add_widget(row)
            self._company_checks.append(row)

    def _checked_company_ids(self) -> list[int]:
        return [row.company_id for row in self._company_checks if row.ids.check.active]

    def _refresh_language_text(self) -> None:
        name = next((n for lid, n in self._language_options if lid == self._language_id), "— انتخاب زبان —")
        self.ids.language_button.text = shape(name)

    def open_language_menu(self) -> None:
        items = [
            {
                "text": shape(name),
                "on_release": lambda lid=lid: (self._menu.dismiss(), self._select_language(lid)),
            }
            for lid, name in self._language_options
        ]
        from peecha.ui.widgets import open_rtl_dropdown  # noqa: PLC0415

        self._menu = open_rtl_dropdown(self.ids.language_button, items, width_mult=3)

    def _select_language(self, language_id: int) -> None:
        self._language_id = language_id
        self._refresh_language_text()

    def _set_status(self, message: str, *, is_error: bool = False) -> None:
        self.ids.status_label.text = shape(message)
        self.ids.status_label.text_color = theme.DANGER if is_error else theme.TEXT_SECONDARY

    def refresh_list(self) -> None:
        self.ids.users_list.clear_widgets()
        from peecha.ui.widgets import PEmptyState  # noqa: PLC0415

        rows = users_service.list_users()
        self._rows_by_id = {r.user_id: r for r in rows}
        self.ids.grid_header.opacity = 1 if rows else 0
        if not rows:
            self.ids.users_list.add_widget(
                PEmptyState(icon="account-multiple-outline", text=shape("هنوز کاربری تعریف نشده است."))
            )
        for i, row in enumerate(rows):
            self.ids.users_list.add_widget(
                UserRowWidget(
                    user_id=row.user_id,
                    on_edit=self.edit_user,
                    username_text=row.username,
                    name_text=shape(row.full_name),
                    role_text=shape("مدیر کل" if row.is_super_admin else "کاربر"),
                    status_text=shape("فعال" if row.is_active else "غیرفعال"),
                    is_active_row=row.is_active,
                    zebra=i % 2 == 1,
                    selected=row.user_id == self._editing_user_id,
                )
            )

    def edit_user(self, user_id: int) -> None:
        row = self._rows_by_id.get(user_id)
        if row is None:
            return
        self._editing_user_id = user_id
        self.ids.username_field.set_value(row.username)
        self.ids.username_field.disabled = True
        self.ids.full_name_field.set_value(row.full_name)
        self.ids.full_name_field.focus = True
        self.ids.email_field.set_value(row.email or "")
        self.ids.password_field.text = ""
        self.ids.password_field.hint_text = shape("رمز عبور جدید (اختیاری)")
        self._language_id = row.default_language_id
        self._refresh_language_text()
        self.ids.is_super_admin_checkbox.active = row.is_super_admin
        self.ids.is_active_checkbox.active = row.is_active
        self._rebuild_company_checklist(set(row.company_ids))
        self.ids.form_title.text = shape(f"ویرایش کاربر «{row.full_name}»")
        self.ids.save_button.text = shape("ذخیره تغییرات")
        self.ids.cancel_edit_button.opacity = 1
        self.ids.cancel_edit_button.disabled = False
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "36dp"
        self._set_status(f"در حال ویرایش «{row.full_name}» — Escape برای لغو.")

    def cancel_edit(self) -> None:
        self._editing_user_id = None
        self.ids.username_field.text = ""
        self.ids.username_field.disabled = False
        self.ids.full_name_field.text = ""
        self.ids.email_field.text = ""
        self.ids.password_field.text = ""
        self.apply_field_labels()
        self.ids.is_super_admin_checkbox.active = False
        self.ids.is_active_checkbox.active = True
        self._rebuild_company_checklist()
        self.ids.form_title.text = shape("افزودن کاربر جدید")
        self.ids.save_button.text = shape("افزودن کاربر")
        self.ids.cancel_edit_button.opacity = 0
        self.ids.cancel_edit_button.disabled = True
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "0dp"
        self._set_status("")

    def save_user(self) -> None:
        full_name = self.ids.full_name_field.value.strip()
        email = self.ids.email_field.value.strip()
        password = self.ids.password_field.text
        company_ids = self._checked_company_ids()
        default_company_id = company_ids[0] if company_ids else None

        if self._editing_user_id is not None:
            if not full_name:
                self._set_status("نام کامل را وارد کنید.")
                return
            try:
                users_service.update_user(
                    user_id=self._editing_user_id,
                    full_name=full_name,
                    email=email,
                    default_language_id=self._language_id,
                    is_super_admin=self.ids.is_super_admin_checkbox.active,
                    is_active=self.ids.is_active_checkbox.active,
                    company_ids=company_ids,
                    default_company_id=default_company_id,
                    new_password=password or None,
                )
            except Exception as exc:  # noqa: BLE001
                self._set_status(f"خطا: {exc}", is_error=True)
                return
            self.cancel_edit()
            self.refresh_list()
            return

        username = self.ids.username_field.value.strip()
        if not username or not full_name or not password:
            self._set_status("نام‌کاربری، نام کامل و رمز عبور را وارد کنید.", is_error=True)
            return
        try:
            users_service.create_user(
                username=username,
                full_name=full_name,
                password=password,
                email=email,
                default_language_id=self._language_id,
                is_super_admin=self.ids.is_super_admin_checkbox.active,
                company_ids=company_ids,
                default_company_id=default_company_id,
            )
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"خطا: {exc}", is_error=True)
            return

        self.cancel_edit()
        self._set_status("کاربر با موفقیت اضافه شد.")
        self.refresh_list()
