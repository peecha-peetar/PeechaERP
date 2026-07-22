"""صفحه‌ی مدیریتِ اشخاص (تفصیلیِ اشخاص) — برخلافِ «مراکز هزینه و ابعادِ
تفصیلی» که کاربر باید اول یک نوع‌بُعد بسازد، اینجا فقط یک فهرستِ ساده از
اشخاص است؛ چون نوع‌بُعدِ «اشخاص» خودش سیستمی/خودکار است (هر شرکت از لحظه‌ی
ساخته‌شدن دارد) و نیازی به مدیریتِ جداگانه ندارد. ردیفِ سیستمیِ «بدون
تفصیلی» همیشه هست و قابلِ ویرایش/حذف نیست — پیش‌فرضِ خودکارِ هر ردیفِ سند
که شخصی برایش انتخاب نشده باشد."""

from __future__ import annotations

import os

from kivy.factory import Factory
from kivy.lang import Builder
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, ObjectProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.screen import MDScreen

from peecha import session
from peecha.services import detail_dimensions as dimensions_service
from peecha.ui import theme
from peecha.ui.i18n import tr
from peecha.ui.rtl import shape
from peecha.ui.shortcuts import KeyboardShortcutMixin

_KV_PATH = os.path.join(os.path.dirname(__file__), "persons.kv")
Builder.load_file(_KV_PATH)


class PersonRowWidget(RecycleDataViewBehavior, ButtonBehavior, MDBoxLayout):
    detail_account_id = NumericProperty(0)
    code_text = StringProperty("")
    name_text = StringProperty("")
    status_text = StringProperty("")
    is_active_row = BooleanProperty(True)
    is_system_row = BooleanProperty(False)
    zebra = BooleanProperty(False)
    selected = BooleanProperty(False)
    on_edit = ObjectProperty(None)
    on_delete = ObjectProperty(None)

    def on_release(self) -> None:
        if self.on_edit is not None:
            self.on_edit(self.detail_account_id)

    def request_delete(self) -> None:
        if not self.is_system_row and self.on_delete is not None:
            self.on_delete(self.detail_account_id)


Factory.register("PersonRowWidget", cls=PersonRowWidget)


class PersonsScreen(KeyboardShortcutMixin, MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._persons_by_id: dict[int, dimensions_service.DetailAccountRow] = {}
        self._editing_person_id: int | None = None
        self._delete_dialog: MDDialog | None = None

    def on_pre_enter(self, *args):
        self.refresh_list()
        self.bind_shortcuts()

    def on_leave(self, *args):
        self.unbind_shortcuts()

    def on_shortcut_save(self) -> None:
        self.save_person()

    def on_shortcut_cancel(self) -> bool:
        if self._editing_person_id is not None:
            self.cancel_edit()
            return True
        return False

    def _current_company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def _set_status(self, message: str, *, is_error: bool = False) -> None:
        self.ids.status_label.text = shape(message)
        self.ids.status_label.text_color = theme.DANGER if is_error else theme.TEXT_SECONDARY

    def refresh_list(self) -> None:
        company_id = self._current_company_id()
        if company_id is None:
            self._set_status(tr("هیچ شرکتی انتخاب نشده است."), is_error=True)
            self.ids.persons_list.data = []
            return

        rows = dimensions_service.list_persons(company_id)
        self._persons_by_id = {r.detail_account_id: r for r in rows}
        if not rows:
            self.ids.persons_list.data = [
                {"viewclass": "PEmptyState", "icon": "account-multiple-outline", "text": shape(tr("هنوز شخصی تعریف نشده است."))}
            ]
            return

        self.ids.persons_list.data = [
            {
                "detail_account_id": row.detail_account_id,
                "on_edit": self.edit_person,
                "on_delete": self.confirm_delete,
                "code_text": row.code,
                "name_text": shape(row.name or "—"),
                "status_text": shape(tr("فعال") if row.is_active else tr("غیرفعال")),
                "is_active_row": row.is_active,
                "is_system_row": row.code == dimensions_service.NO_DETAIL_CODE,
                "zebra": i % 2 == 1,
                "selected": row.detail_account_id == self._editing_person_id,
            }
            for i, row in enumerate(rows)
        ]

    def edit_person(self, detail_account_id: int) -> None:
        row = self._persons_by_id.get(detail_account_id)
        if row is None:
            return
        if row.code == dimensions_service.NO_DETAIL_CODE:
            self._set_status(tr("کدِ سیستمیِ «بدون تفصیلی» قابلِ ویرایش نیست."), is_error=True)
            return
        self._editing_person_id = detail_account_id
        self.ids.code_field.set_value(row.code)
        self.ids.name_field.set_value(row.name or "")
        self.ids.active_checkbox.active = row.is_active
        self.ids.form_title.text = shape(tr("ویرایشِ شخصِ «{}»").format(row.name or row.code))
        self.ids.save_button.text = shape(tr("ذخیره تغییرات"))
        self.ids.cancel_edit_button.opacity = 1
        self.ids.cancel_edit_button.disabled = False
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "36dp"
        self._set_status(tr("در حال ویرایش «{}» — Escape برای لغو.").format(row.name or row.code))
        self.refresh_list()

    def cancel_edit(self) -> None:
        self._editing_person_id = None
        self.ids.code_field.text = ""
        self.ids.name_field.text = ""
        self.ids.active_checkbox.active = True
        self.ids.form_title.text = shape(tr("افزودنِ شخصِ تازه"))
        self.ids.save_button.text = shape(tr("افزودن"))
        self.ids.cancel_edit_button.opacity = 0
        self.ids.cancel_edit_button.disabled = True
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "0dp"
        self._set_status(tr(""))
        self.refresh_list()

    def save_person(self) -> None:
        company_id = self._current_company_id()
        if company_id is None:
            self._set_status(tr("هیچ شرکتی انتخاب نشده است."), is_error=True)
            return

        code = self.ids.code_field.value.strip()
        name = self.ids.name_field.value.strip()
        if not code or not name:
            self._set_status(tr("کد و نامِ شخص را وارد کنید."), is_error=True)
            return

        if self._editing_person_id is not None:
            try:
                dimensions_service.update_person(
                    detail_account_id=self._editing_person_id,
                    company_id=company_id,
                    code=code,
                    name=name,
                    is_active=self.ids.active_checkbox.active,
                )
            except Exception as exc:  # noqa: BLE001 - نمایش هر خطای دیتابیس به کاربر
                self._set_status(tr("خطا: {}").format(exc), is_error=True)
                return
            self.cancel_edit()
            return

        try:
            dimensions_service.create_person(company_id=company_id, code=code, name=name)
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc), is_error=True)
            return
        self.ids.code_field.text = ""
        self.ids.name_field.text = ""
        self._set_status(tr("شخص افزوده شد."))
        self.refresh_list()

    def confirm_delete(self, detail_account_id: int) -> None:
        row = self._persons_by_id.get(detail_account_id)
        if row is None:
            return
        if self._delete_dialog is not None:
            self._delete_dialog.dismiss()

        def _do_delete(*_args) -> None:
            self._delete_dialog.dismiss()
            self._perform_delete(detail_account_id)

        self._delete_dialog = MDDialog(
            title=shape(tr("حذفِ شخص")),
            text=shape(tr("شخصِ «{}» حذف شود؟ این کار قابل بازگشت نیست.").format(row.name or row.code)),
            buttons=[
                MDFlatButton(text=shape(tr("لغو")), on_release=lambda *_: self._delete_dialog.dismiss()),
                MDRaisedButton(text=shape(tr("حذف")), md_bg_color=theme.DANGER, on_release=_do_delete),
            ],
        )
        self._delete_dialog.open()

    def _perform_delete(self, detail_account_id: int) -> None:
        company_id = self._current_company_id()
        if company_id is None:
            return
        try:
            dimensions_service.delete_person(detail_account_id, company_id)
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc), is_error=True)
            return
        if self._editing_person_id == detail_account_id:
            self.cancel_edit()
        else:
            self._set_status(tr("شخص حذف شد."))
            self.refresh_list()
