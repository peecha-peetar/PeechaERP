"""صفحه‌ی نقش‌ها و دسترسی‌ها — تعریفِ نقش‌های درختیِ شرکتِ جاری، برای هر نقش
یک شبکه‌ی دسترسیِ VIEW/CREATE/EDIT/DELETE روی فرم‌های برنامه (سرویس roles.py،
جدول sec.role_form_permissions)، و تخصیصِ کاربران به نقش (sec.user_roles).
هر تغییرِ چک‌باکسِ دسترسی/تخصیص بلافاصله ذخیره می‌شود (بدون دکمه‌ی ذخیره‌ی
جدا) — چون هرکدام مستقل و کوچک است، شبیهِ toggle باز/بسته‌کردنِ سال مالی."""

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
from peecha.services import roles as roles_service
from peecha.ui import theme
from peecha.ui.i18n import tr
from peecha.ui.rtl import shape
from peecha.ui.shortcuts import KeyboardShortcutMixin

_KV_PATH = os.path.join(os.path.dirname(__file__), "roles.kv")
Builder.load_file(_KV_PATH)

_NO_PARENT_LABEL = "— بدون والد —"
_ACTIONS = ["VIEW", "CREATE", "EDIT", "DELETE"]


class RoleRowWidget(ButtonBehavior, MDBoxLayout):
    code_text = StringProperty("")
    parent_text = StringProperty("")
    status_text = StringProperty("")
    is_active_row = BooleanProperty(True)
    zebra = BooleanProperty(False)
    selected = BooleanProperty(False)

    def __init__(self, role_id: int, on_edit, **kwargs):
        super().__init__(**kwargs)
        self.role_id = role_id
        self._on_edit = on_edit

    def on_release(self) -> None:
        self._on_edit(self.role_id)


class _PermissionRow(MDBoxLayout):
    label_text = StringProperty("")

    def __init__(self, form_id: int, on_toggle, **kwargs):
        super().__init__(**kwargs)
        self.form_id = form_id
        self._on_toggle = on_toggle

    def toggle(self, action_code: str, active: bool) -> None:
        self._on_toggle(self.form_id, action_code, active)


class _RoleUserRow(MDBoxLayout):
    label_text = StringProperty("")

    def __init__(self, user_id: int, on_toggle, **kwargs):
        super().__init__(**kwargs)
        self.user_id = user_id
        self._on_toggle = on_toggle

    def toggle(self, active: bool) -> None:
        self._on_toggle(self.user_id, active)


class RolesScreen(KeyboardShortcutMixin, MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._rows_by_id: dict[int, roles_service.RoleRow] = {}
        self._role_options: list[roles_service.RoleRow] = []
        self._forms: list[roles_service.FormOption] = []
        self._parent_role_id: int | None = None
        self._editing_role_id: int | None = None
        self._menu: MDDropdownMenu | None = None

    def on_pre_enter(self, *args):
        self._forms = roles_service.list_forms()
        self.apply_field_labels()
        self.refresh_list()
        # طبق درخواستِ صریح: با برگشتن به این صفحه، انتخابِ والد/شبکه‌ی
        # دسترسی/تخصیصِ کاربرانِ نیمه‌کاره نباید پاک شود — با وضعیتِ فعلی
        # (نه با None ثابت) دوباره ساخته می‌شود.
        self._select_parent(self._parent_role_id)
        self._build_permissions_grid(self._editing_role_id)
        self._build_users_checklist(self._editing_role_id)
        self.bind_shortcuts()

    def on_leave(self, *args):
        self.unbind_shortcuts()

    def apply_field_labels(self) -> None:
        language_id = session.current_language.language_id if session.current_language else None
        labels = {k: tr(v) for k, v in field_labels_service.get_labels_map("roles", language_id).items()}
        self.ids.code_field.hint_text = shape(labels["code"])

    def on_shortcut_save(self) -> None:
        self.save_role()

    def on_shortcut_cancel(self) -> bool:
        if self._editing_role_id is not None:
            self.cancel_edit()
            return True
        return False

    def _set_status(self, message: str, *, is_error: bool = False) -> None:
        self.ids.status_label.text = shape(message)
        self.ids.status_label.text_color = theme.DANGER if is_error else theme.TEXT_SECONDARY

    def _current_company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def open_parent_menu(self) -> None:
        items = [
            {"text": shape(tr(_NO_PARENT_LABEL)), "on_release": lambda: (self._menu.dismiss(), self._select_parent(None))}
        ]
        for row in self._role_options:
            if row.role_id == self._editing_role_id:
                continue  # نقش نمی‌تواند والدِ خودش باشد
            items.append(
                {
                    "text": shape(row.code),
                    "on_release": lambda rid=row.role_id: (self._menu.dismiss(), self._select_parent(rid)),
                }
            )
        from peecha.ui.widgets import open_rtl_dropdown  # noqa: PLC0415

        self._menu = open_rtl_dropdown(self.ids.parent_button, items, width_mult=3)

    def _select_parent(self, role_id: int | None) -> None:
        self._parent_role_id = role_id
        if role_id is None:
            self.ids.parent_button.text = shape(tr(_NO_PARENT_LABEL))
            return
        parent = next((r for r in self._role_options if r.role_id == role_id), None)
        self.ids.parent_button.text = shape(parent.code if parent else tr(_NO_PARENT_LABEL))

    def refresh_list(self) -> None:
        self.ids.roles_list.clear_widgets()
        company_id = self._current_company_id()
        if company_id is None:
            self._set_status(tr("هیچ شرکتی انتخاب نشده است."), is_error=True)
            return

        from peecha.ui.widgets import PEmptyState  # noqa: PLC0415

        rows = roles_service.list_roles(company_id)
        self._rows_by_id = {r.role_id: r for r in rows}
        self._role_options = rows
        if not rows:
            self.ids.roles_list.add_widget(
                PEmptyState(icon="shield-account-outline", text=shape(tr("هنوز نقشی تعریف نشده است.")))
            )
        for i, row in enumerate(rows):
            self.ids.roles_list.add_widget(
                RoleRowWidget(
                    role_id=row.role_id,
                    on_edit=self.edit_role,
                    code_text=row.code,
                    parent_text=shape(row.parent_code or "—"),
                    status_text=shape(tr("فعال") if row.is_active else tr("غیرفعال")),
                    is_active_row=row.is_active,
                    zebra=i % 2 == 1,
                    selected=row.role_id == self._editing_role_id,
                )
            )

    def edit_role(self, role_id: int) -> None:
        row = self._rows_by_id.get(role_id)
        if row is None:
            return
        self._editing_role_id = role_id
        self.ids.code_field.set_value(row.code)
        self.ids.code_field.disabled = True
        self._select_parent(row.parent_role_id)
        self.ids.is_active_checkbox.active = row.is_active
        self.ids.form_title.text = shape(tr("ویرایش نقش «{}»").format(row.code))
        self.ids.save_button.text = shape(tr("ذخیره تغییرات"))
        self.ids.cancel_edit_button.opacity = 1
        self.ids.cancel_edit_button.disabled = False
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "36dp"
        self._set_status(tr("در حال ویرایش «{}» — Escape برای لغو.").format(row.code))
        self._build_permissions_grid(role_id)
        self._build_users_checklist(role_id)
        self.refresh_list()

    def cancel_edit(self) -> None:
        self._editing_role_id = None
        self.ids.code_field.text = ""
        self.ids.code_field.disabled = False
        self._select_parent(None)
        self.ids.is_active_checkbox.active = True
        self.ids.form_title.text = shape(tr("افزودن نقش جدید"))
        self.ids.save_button.text = shape(tr("افزودن نقش"))
        self.ids.cancel_edit_button.opacity = 0
        self.ids.cancel_edit_button.disabled = True
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "0dp"
        self._set_status(tr(""))
        self._build_permissions_grid(None)
        self._build_users_checklist(None)
        self.refresh_list()

    def save_role(self) -> None:
        company_id = self._current_company_id()
        if company_id is None:
            self._set_status(tr("هیچ شرکتی انتخاب نشده است."), is_error=True)
            return

        if self._editing_role_id is not None:
            try:
                roles_service.update_role(
                    role_id=self._editing_role_id,
                    company_id=company_id,
                    parent_role_id=self._parent_role_id,
                    is_active=self.ids.is_active_checkbox.active,
                )
            except Exception as exc:  # noqa: BLE001
                self._set_status(tr("خطا: {}").format(exc), is_error=True)
                return
            self.cancel_edit()
            return

        code = self.ids.code_field.value.strip()
        if not code:
            self._set_status(tr("کدِ نقش را وارد کنید."), is_error=True)
            return
        try:
            role = roles_service.create_role(company_id=company_id, code=code, parent_role_id=self._parent_role_id)
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc), is_error=True)
            return
        self._set_status(f"نقش «{role.code}» ساخته شد؛ حالا دسترسی‌های آن را تنظیم کنید.")
        self.refresh_list()
        self.edit_role(role.role_id)

    # --- شبکه‌ی دسترسی (VIEW/CREATE/EDIT/DELETE روی هر فرم) ------------------

    def _build_permissions_grid(self, role_id: int | None) -> None:
        self.ids.permissions_grid_box.clear_widgets()
        if role_id is None:
            from peecha.ui.widgets import PEmptyState  # noqa: PLC0415

            self.ids.permissions_grid_box.add_widget(
                PEmptyState(
                    icon="shield-off-outline",
                    text=shape(tr("ابتدا یک نقش را ذخیره یا برای ویرایش انتخاب کنید.")),
                )
            )
            return
        allowed = roles_service.get_role_permissions(role_id)
        for form in self._forms:
            row = _PermissionRow(
                form_id=form.form_id,
                on_toggle=lambda form_id, action_code, active: self._set_permission(role_id, form_id, action_code, active),
                label_text=shape(
                    f"{tr(roles_service.MODULE_LABELS.get(form.module_code, form.module_code))} — {tr(form.label)}"
                ),
            )
            for action_code in _ACTIONS:
                checkbox = row.ids[f"check_{action_code.lower()}"]
                checkbox.active = (form.form_id, action_code) in allowed
                checkbox.bind(
                    active=lambda _inst, active, r=row, a=action_code: r.toggle(a, active)
                )
            self.ids.permissions_grid_box.add_widget(row)

    def _set_permission(self, role_id: int, form_id: int, action_code: str, is_allowed: bool) -> None:
        try:
            roles_service.set_role_permission(role_id, form_id, action_code, is_allowed)
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc), is_error=True)

    # --- تخصیصِ کاربران به نقش ------------------------------------------------

    def _build_users_checklist(self, role_id: int | None) -> None:
        self.ids.role_users_box.clear_widgets()
        company_id = self._current_company_id()
        if role_id is None or company_id is None:
            from peecha.ui.widgets import PEmptyState  # noqa: PLC0415

            self.ids.role_users_box.add_widget(
                PEmptyState(icon="account-off-outline", text=shape(tr("نقشی برای تخصیصِ کاربر انتخاب نشده است.")))
            )
            return
        rows = roles_service.list_role_users(role_id, company_id)
        for user_row in rows:
            row = _RoleUserRow(
                user_id=user_row.user_id,
                on_toggle=lambda user_id, active: self._set_user_role(role_id, user_id, active),
                label_text=shape(user_row.full_name),
            )
            row.ids.check.active = user_row.assigned
            row.ids.check.bind(active=lambda _inst, active, r=row: r.toggle(active))
            self.ids.role_users_box.add_widget(row)

    def _set_user_role(self, role_id: int, user_id: int, assigned: bool) -> None:
        company_id = self._current_company_id()
        if company_id is None:
            return
        try:
            roles_service.set_user_role(user_id, role_id, company_id, assigned)
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc), is_error=True)
