"""صفحه‌ی مدیریتِ ابعادِ تفصیلی/مراکزِ هزینه.

پنلِ راست: فهرستِ «نوع‌بُعد»ها (مثلِ مرکزِ هزینه، پروژه، مشتری) — هرکدام
یک ردیف در acc.detail_dimension_types. با انتخابِ یک نوع‌بُعد، پنلِ چپ
حساب‌های تفصیلیِ همان نوع را نشان می‌دهد (acc.detail_accounts) — دقیقاً
همان الگویِ فهرست/فرمِ اصلی‌شده در chart_of_accounts.py/roles.py، فقط
تودرتو (نوع‌بُعد → حساب‌های تفصیلی‌اش)."""

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

_KV_PATH = os.path.join(os.path.dirname(__file__), "detail_dimensions.kv")
Builder.load_file(_KV_PATH)


class DimensionTypeRowWidget(RecycleDataViewBehavior, ButtonBehavior, MDBoxLayout):
    dimension_type_id = NumericProperty(0)
    code_text = StringProperty("")
    count_text = StringProperty("")
    status_text = StringProperty("")
    is_active_row = BooleanProperty(True)
    zebra = BooleanProperty(False)
    selected = BooleanProperty(False)
    on_edit = ObjectProperty(None)
    on_delete = ObjectProperty(None)

    def on_release(self) -> None:
        if self.on_edit is not None:
            self.on_edit(self.dimension_type_id)

    def request_delete(self) -> None:
        if self.on_delete is not None:
            self.on_delete(self.dimension_type_id)


Factory.register("DimensionTypeRowWidget", cls=DimensionTypeRowWidget)


class DetailAccountRowWidget(RecycleDataViewBehavior, ButtonBehavior, MDBoxLayout):
    detail_account_id = NumericProperty(0)
    code_text = StringProperty("")
    status_text = StringProperty("")
    is_active_row = BooleanProperty(True)
    zebra = BooleanProperty(False)
    selected = BooleanProperty(False)
    on_edit = ObjectProperty(None)
    on_delete = ObjectProperty(None)

    def on_release(self) -> None:
        if self.on_edit is not None:
            self.on_edit(self.detail_account_id)

    def request_delete(self) -> None:
        if self.on_delete is not None:
            self.on_delete(self.detail_account_id)


Factory.register("DetailAccountRowWidget", cls=DetailAccountRowWidget)


class DetailDimensionsScreen(KeyboardShortcutMixin, MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._types_by_id: dict[int, dimensions_service.DimensionTypeRow] = {}
        self._editing_type_id: int | None = None
        self._selected_type_id: int | None = None
        self._accounts_by_id: dict[int, dimensions_service.DetailAccountRow] = {}
        self._editing_account_id: int | None = None
        self._delete_dialog: MDDialog | None = None

    def on_pre_enter(self, *args):
        self.refresh_types()
        self.bind_shortcuts()

    def on_leave(self, *args):
        self.unbind_shortcuts()

    def on_shortcut_save(self) -> None:
        if self._selected_type_id is not None and self.ids.account_code_field.focus:
            self.save_detail_account()
        else:
            self.save_dimension_type()

    def on_shortcut_cancel(self) -> bool:
        if self._editing_account_id is not None:
            self.cancel_account_edit()
            return True
        if self._editing_type_id is not None:
            self.cancel_type_edit()
            return True
        return False

    def _current_company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def _set_status(self, message: str, *, is_error: bool = False) -> None:
        self.ids.status_label.text = shape(message)
        self.ids.status_label.text_color = theme.DANGER if is_error else theme.TEXT_SECONDARY

    def _set_account_status(self, message: str, *, is_error: bool = False) -> None:
        self.ids.account_status_label.text = shape(message)
        self.ids.account_status_label.text_color = theme.DANGER if is_error else theme.TEXT_SECONDARY

    # --- نوع‌بُعدها -----------------------------------------------------------

    def refresh_types(self) -> None:
        company_id = self._current_company_id()
        if company_id is None:
            self._set_status(tr("هیچ شرکتی انتخاب نشده است."), is_error=True)
            self.ids.types_list.data = []
            return

        rows = dimensions_service.list_dimension_types(company_id)
        self._types_by_id = {r.dimension_type_id: r for r in rows}
        if not rows:
            self.ids.types_list.data = [
                {
                    "viewclass": "PEmptyState",
                    "icon": "shape-outline",
                    "text": shape(tr("هنوز نوع‌بُعدی (مثلاً مرکز هزینه) تعریف نشده است.")),
                }
            ]
        else:
            self.ids.types_list.data = [
                {
                    "dimension_type_id": row.dimension_type_id,
                    "on_edit": self.edit_dimension_type,
                    "on_delete": self.confirm_delete_type,
                    "code_text": row.code,
                    "count_text": str(row.detail_account_count),
                    "status_text": shape(tr("فعال") if row.is_active else tr("غیرفعال")),
                    "is_active_row": row.is_active,
                    "zebra": i % 2 == 1,
                    "selected": row.dimension_type_id == self._editing_type_id,
                }
                for i, row in enumerate(rows)
            ]

        if self._selected_type_id is not None and self._selected_type_id not in self._types_by_id:
            self._select_type(None)
        elif self._selected_type_id is not None:
            self.refresh_accounts()

    def edit_dimension_type(self, dimension_type_id: int) -> None:
        row = self._types_by_id.get(dimension_type_id)
        if row is None:
            return
        self._editing_type_id = dimension_type_id
        self.ids.type_code_field.set_value(row.code)
        self.ids.type_active_checkbox.active = row.is_active
        self.ids.type_form_title.text = shape(tr("ویرایش نوع‌بُعد «{}»").format(row.code))
        self.ids.type_save_button.text = shape(tr("ذخیره تغییرات"))
        self.ids.type_cancel_button.opacity = 1
        self.ids.type_cancel_button.disabled = False
        self.ids.type_cancel_button.size_hint_y = None
        self.ids.type_cancel_button.height = "36dp"
        self._set_status(tr("در حال ویرایش «{}» — Escape برای لغو.").format(row.code))
        self.refresh_types()
        self._select_type(dimension_type_id)

    def cancel_type_edit(self) -> None:
        self._editing_type_id = None
        self.ids.type_code_field.text = ""
        self.ids.type_active_checkbox.active = True
        self.ids.type_form_title.text = shape(tr("افزودنِ نوع‌بُعدِ تازه"))
        self.ids.type_save_button.text = shape(tr("افزودن"))
        self.ids.type_cancel_button.opacity = 0
        self.ids.type_cancel_button.disabled = True
        self.ids.type_cancel_button.size_hint_y = None
        self.ids.type_cancel_button.height = "0dp"
        self._set_status(tr(""))
        self.refresh_types()

    def save_dimension_type(self) -> None:
        company_id = self._current_company_id()
        if company_id is None:
            self._set_status(tr("هیچ شرکتی انتخاب نشده است."), is_error=True)
            return

        if self._editing_type_id is not None:
            code = self.ids.type_code_field.value.strip()
            if not code:
                self._set_status(tr("کدِ نوع‌بُعد را وارد کنید."), is_error=True)
                return
            try:
                dimensions_service.update_dimension_type(
                    dimension_type_id=self._editing_type_id,
                    company_id=company_id,
                    code=code,
                    is_active=self.ids.type_active_checkbox.active,
                )
            except Exception as exc:  # noqa: BLE001 - نمایش هر خطای دیتابیس به کاربر
                self._set_status(tr("خطا: {}").format(exc), is_error=True)
                return
            self.cancel_type_edit()
            return

        code = self.ids.type_code_field.value.strip()
        if not code:
            self._set_status(tr("کدِ نوع‌بُعد را وارد کنید."), is_error=True)
            return
        try:
            dimension_type = dimensions_service.create_dimension_type(company_id=company_id, code=code)
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc), is_error=True)
            return
        self.ids.type_code_field.text = ""
        self._set_status(f"نوع‌بُعد «{dimension_type.code}» ساخته شد؛ حالا حساب‌های تفصیلیِ آن را اضافه کنید.")
        self.refresh_types()
        self._select_type(dimension_type.dimension_type_id)

    def confirm_delete_type(self, dimension_type_id: int) -> None:
        row = self._types_by_id.get(dimension_type_id)
        if row is None:
            return
        if self._delete_dialog is not None:
            self._delete_dialog.dismiss()

        def _do_delete(*_args) -> None:
            self._delete_dialog.dismiss()
            self._perform_delete_type(dimension_type_id)

        self._delete_dialog = MDDialog(
            title=shape(tr("حذف نوع‌بُعد")),
            text=shape(tr("نوع‌بُعد «{}» حذف شود؟ این کار قابل بازگشت نیست.").format(row.code)),
            buttons=[
                MDFlatButton(text=shape(tr("لغو")), on_release=lambda *_: self._delete_dialog.dismiss()),
                MDRaisedButton(text=shape(tr("حذف")), md_bg_color=theme.DANGER, on_release=_do_delete),
            ],
        )
        self._delete_dialog.open()

    def _perform_delete_type(self, dimension_type_id: int) -> None:
        company_id = self._current_company_id()
        if company_id is None:
            return
        try:
            dimensions_service.delete_dimension_type(dimension_type_id, company_id)
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc), is_error=True)
            return
        if self._editing_type_id == dimension_type_id:
            self.cancel_type_edit()
        else:
            self._set_status(tr("نوع‌بُعد حذف شد."))
            self.refresh_types()

    # --- حساب‌های تفصیلیِ نوع‌بُعدِ انتخاب‌شده ----------------------------------

    def _select_type(self, dimension_type_id: int | None) -> None:
        self._selected_type_id = dimension_type_id
        self._editing_account_id = None
        self.ids.account_code_field.text = ""
        self.ids.account_active_checkbox.active = True
        self.ids.account_save_button.text = shape(tr("افزودن"))
        self.ids.account_cancel_button.opacity = 0
        self.ids.account_cancel_button.disabled = True
        self.ids.account_cancel_button.size_hint_y = None
        self.ids.account_cancel_button.height = "0dp"
        self._set_account_status(tr(""))
        if dimension_type_id is None:
            self.ids.accounts_panel.opacity = 0
            self.ids.accounts_panel.disabled = True
            self.ids.accounts_empty_label.opacity = 1
            self.ids.accounts_list.data = []
            return
        row = self._types_by_id.get(dimension_type_id)
        self.ids.accounts_panel.opacity = 1
        self.ids.accounts_panel.disabled = False
        self.ids.accounts_empty_label.opacity = 0
        self.ids.accounts_title.text = shape(tr("حساب‌های تفصیلیِ «{}»").format(row.code if row else ""))
        self.refresh_accounts()

    def refresh_accounts(self) -> None:
        company_id = self._current_company_id()
        if company_id is None or self._selected_type_id is None:
            self.ids.accounts_list.data = []
            return
        rows = dimensions_service.list_detail_accounts(company_id, self._selected_type_id)
        self._accounts_by_id = {r.detail_account_id: r for r in rows}
        if not rows:
            self.ids.accounts_list.data = [
                {
                    "viewclass": "PEmptyState",
                    "icon": "shape-plus-outline",
                    "text": shape(tr("هنوز حسابِ تفصیلی‌ای برای این نوع‌بُعد تعریف نشده است.")),
                }
            ]
        else:
            self.ids.accounts_list.data = [
                {
                    "detail_account_id": row.detail_account_id,
                    "on_edit": self.edit_detail_account,
                    "on_delete": self.confirm_delete_account,
                    "code_text": row.code,
                    "status_text": shape(tr("فعال") if row.is_active else tr("غیرفعال")),
                    "is_active_row": row.is_active,
                    "zebra": i % 2 == 1,
                    "selected": row.detail_account_id == self._editing_account_id,
                }
                for i, row in enumerate(rows)
            ]
        if self._editing_account_id is not None and self._editing_account_id not in self._accounts_by_id:
            self.cancel_account_edit()

    def edit_detail_account(self, detail_account_id: int) -> None:
        row = self._accounts_by_id.get(detail_account_id)
        if row is None:
            return
        self._editing_account_id = detail_account_id
        self.ids.account_code_field.set_value(row.code)
        self.ids.account_active_checkbox.active = row.is_active
        self.ids.account_save_button.text = shape(tr("ذخیره تغییرات"))
        self.ids.account_cancel_button.opacity = 1
        self.ids.account_cancel_button.disabled = False
        self.ids.account_cancel_button.size_hint_y = None
        self.ids.account_cancel_button.height = "36dp"
        self._set_account_status(tr("در حال ویرایش «{}» — Escape برای لغو.").format(row.code))
        self.refresh_accounts()

    def cancel_account_edit(self) -> None:
        self._editing_account_id = None
        self.ids.account_code_field.text = ""
        self.ids.account_active_checkbox.active = True
        self.ids.account_save_button.text = shape(tr("افزودن"))
        self.ids.account_cancel_button.opacity = 0
        self.ids.account_cancel_button.disabled = True
        self.ids.account_cancel_button.size_hint_y = None
        self.ids.account_cancel_button.height = "0dp"
        self._set_account_status(tr(""))
        self.refresh_accounts()

    def save_detail_account(self) -> None:
        company_id = self._current_company_id()
        if company_id is None or self._selected_type_id is None:
            self._set_account_status(tr("ابتدا یک نوع‌بُعد را انتخاب کنید."), is_error=True)
            return

        code = self.ids.account_code_field.value.strip()
        if not code:
            self._set_account_status(tr("کدِ حسابِ تفصیلی را وارد کنید."), is_error=True)
            return

        if self._editing_account_id is not None:
            try:
                dimensions_service.update_detail_account(
                    detail_account_id=self._editing_account_id,
                    company_id=company_id,
                    code=code,
                    is_active=self.ids.account_active_checkbox.active,
                )
            except Exception as exc:  # noqa: BLE001
                self._set_account_status(tr("خطا: {}").format(exc), is_error=True)
                return
            self.cancel_account_edit()
            self.refresh_types()
            return

        try:
            dimensions_service.create_detail_account(
                company_id=company_id, dimension_type_id=self._selected_type_id, code=code
            )
        except Exception as exc:  # noqa: BLE001
            self._set_account_status(tr("خطا: {}").format(exc), is_error=True)
            return
        self.ids.account_code_field.text = ""
        self._set_account_status(tr("حسابِ تفصیلی افزوده شد."))
        self.refresh_accounts()
        self.refresh_types()

    def confirm_delete_account(self, detail_account_id: int) -> None:
        row = self._accounts_by_id.get(detail_account_id)
        if row is None:
            return
        if self._delete_dialog is not None:
            self._delete_dialog.dismiss()

        def _do_delete(*_args) -> None:
            self._delete_dialog.dismiss()
            self._perform_delete_account(detail_account_id)

        self._delete_dialog = MDDialog(
            title=shape(tr("حذف حسابِ تفصیلی")),
            text=shape(tr("حسابِ تفصیلیِ «{}» حذف شود؟ این کار قابل بازگشت نیست.").format(row.code)),
            buttons=[
                MDFlatButton(text=shape(tr("لغو")), on_release=lambda *_: self._delete_dialog.dismiss()),
                MDRaisedButton(text=shape(tr("حذف")), md_bg_color=theme.DANGER, on_release=_do_delete),
            ],
        )
        self._delete_dialog.open()

    def _perform_delete_account(self, detail_account_id: int) -> None:
        company_id = self._current_company_id()
        if company_id is None:
            return
        try:
            dimensions_service.delete_detail_account(detail_account_id, company_id)
        except Exception as exc:  # noqa: BLE001
            self._set_account_status(tr("خطا: {}").format(exc), is_error=True)
            return
        if self._editing_account_id == detail_account_id:
            self.cancel_account_edit()
        else:
            self._set_account_status(tr("حسابِ تفصیلی حذف شد."))
            self.refresh_accounts()
        self.refresh_types()
