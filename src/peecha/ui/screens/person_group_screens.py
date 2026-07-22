"""صفحاتِ اختصاصیِ سه گروهِ تفصیلیِ اشخاص: مشتریان، تامین‌کنندگان، پرسنل.

طبق درخواستِ صریح: به‌جای یک فرمِ عمومیِ «شخص»، هر شخص باید به یکی از این
سه گروه تعلق داشته باشد و تعریف/ویرایشش فقط از فرمِ اختصاصیِ همان گروه
انجام شود — هر گروه فیلدهای تکمیلیِ خودش را دارد (جدولِ acc.*_details).
سه کلاس زیر منطقِ مشترک را از PersonGroupScreenBase به ارث می‌برند و فقط
سرویس/فیلدهای اختصاصیِ خودشان را مشخص می‌کنند."""

from __future__ import annotations

import os

from kivy.factory import Factory
from kivy.lang import Builder
from kivy.properties import BooleanProperty, NumericProperty, ObjectProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.screen import MDScreen

from peecha import session
from peecha.services import detail_dimensions as dimensions_service
from peecha.ui import numerals, theme
from peecha.ui.i18n import tr
from peecha.ui.rtl import shape
from peecha.ui.shortcuts import KeyboardShortcutMixin

_KV_PATH = os.path.join(os.path.dirname(__file__), "person_group_screens.kv")
Builder.load_file(_KV_PATH)


class PersonRowWidget(RecycleDataViewBehavior, ButtonBehavior, MDBoxLayout):
    """ردیفِ فهرست — مشترک بینِ هر سه صفحه (فقط کد/نام/وضعیت لازم است،
    جزئیاتِ تکمیلی فقط در فرمِ سمتِ راست دیده می‌شود)."""

    detail_account_id = NumericProperty(0)
    code_text = StringProperty("")
    name_text = StringProperty("")
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


Factory.register("PersonRowWidget", cls=PersonRowWidget)


class PersonGroupScreenBase(KeyboardShortcutMixin, MDScreen):
    """منطقِ مشترکِ سه صفحه: فهرست + فرمِ افزودن/ویرایش. زیرکلاس‌ها فقط
    FIELD_SPECS (فیلدهای تکمیلیِ خودشان) و چهار متدِ سرویس را مشخص می‌کنند."""

    # (kv_id, service_key, kind) — kind یکی از "text"/"decimal"/"date"
    FIELD_SPECS: tuple[tuple[str, str, str], ...] = ()
    EMPTY_ICON = "account-outline"
    EMPTY_TEXT = ""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._rows_by_id: dict[int, dict] = {}
        self._editing_id: int | None = None
        self._delete_dialog: MDDialog | None = None

    def on_pre_enter(self, *args):
        self.refresh_list()
        self.bind_shortcuts()

    def on_leave(self, *args):
        self.unbind_shortcuts()

    def on_shortcut_save(self) -> None:
        self.save_person()

    def on_shortcut_cancel(self) -> bool:
        if self._editing_id is not None:
            self.cancel_edit()
            return True
        return False

    def _current_company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def _set_status(self, message: str, *, is_error: bool = False) -> None:
        self.ids.status_label.text = shape(message)
        self.ids.status_label.text_color = theme.DANGER if is_error else theme.TEXT_SECONDARY

    # --- هوک‌های سرویس، هرکدام در زیرکلاس پیاده می‌شود -----------------

    def _list_rows(self, company_id: int) -> list[dict]:
        raise NotImplementedError

    def _create(self, company_id: int, code: str, name: str, extra: dict) -> None:
        raise NotImplementedError

    def _update(self, detail_account_id: int, company_id: int, code: str, name: str, is_active: bool, extra: dict) -> None:
        raise NotImplementedError

    def _delete(self, detail_account_id: int, company_id: int) -> None:
        raise NotImplementedError

    # --- منطقِ مشترک -----------------------------------------------------

    def _collect_extra_fields(self) -> dict:
        extra: dict = {}
        for kv_id, key, kind in self.FIELD_SPECS:
            widget = self.ids[kv_id]
            text = (widget.value if hasattr(widget, "value") else widget.text).strip()
            if kind == "decimal":
                try:
                    extra[key] = numerals.parse_decimal(text) if text else None
                except ValueError:
                    extra[key] = None
            elif kind == "date":
                try:
                    extra[key] = numerals.parse_jalali_date(text) if text else None
                except ValueError:
                    extra[key] = None
            else:
                extra[key] = text or None
        return extra

    def _populate_extra_fields(self, row: dict) -> None:
        for kv_id, key, kind in self.FIELD_SPECS:
            widget = self.ids[kv_id]
            value = row.get(key)
            if kind == "date" and value:
                text = numerals.format_jalali_date(value)
            elif kind == "decimal" and value is not None:
                text = numerals.to_persian_digits(str(value))
            elif value is not None:
                text = str(value)
            else:
                text = ""
            if hasattr(widget, "set_value"):
                widget.set_value(text)
            else:
                widget.text = text

    def _clear_extra_fields(self) -> None:
        for kv_id, _key, _kind in self.FIELD_SPECS:
            self.ids[kv_id].text = ""

    def refresh_list(self) -> None:
        company_id = self._current_company_id()
        if company_id is None:
            self._set_status(tr("هیچ شرکتی انتخاب نشده است."), is_error=True)
            self.ids.persons_list.data = []
            return

        rows = self._list_rows(company_id)
        self._rows_by_id = {r["detail_account_id"]: r for r in rows}
        if not rows:
            self.ids.persons_list.data = [
                {"viewclass": "PEmptyState", "icon": self.EMPTY_ICON, "text": shape(tr(self.EMPTY_TEXT))}
            ]
            return

        self.ids.persons_list.data = [
            {
                "detail_account_id": row["detail_account_id"],
                "on_edit": self.edit_person,
                "on_delete": self.confirm_delete,
                "code_text": row["code"],
                "name_text": shape(row["name"] or "—"),
                "status_text": shape(tr("فعال") if row["is_active"] else tr("غیرفعال")),
                "is_active_row": row["is_active"],
                "zebra": i % 2 == 1,
                "selected": row["detail_account_id"] == self._editing_id,
            }
            for i, row in enumerate(rows)
        ]

    def edit_person(self, detail_account_id: int) -> None:
        row = self._rows_by_id.get(detail_account_id)
        if row is None:
            return
        self._editing_id = detail_account_id
        self.ids.code_field.set_value(row["code"])
        self.ids.name_field.set_value(row["name"] or "")
        self.ids.active_checkbox.active = row["is_active"]
        self._populate_extra_fields(row)
        self.ids.form_title.text = shape(tr("ویرایشِ «{}»").format(row["name"] or row["code"]))
        self.ids.save_button.text = shape(tr("ذخیره تغییرات"))
        self.ids.cancel_edit_button.opacity = 1
        self.ids.cancel_edit_button.disabled = False
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "36dp"
        self._set_status(tr("در حال ویرایش «{}» — Escape برای لغو.").format(row["name"] or row["code"]))
        self.refresh_list()

    def cancel_edit(self) -> None:
        self._editing_id = None
        self.ids.code_field.text = ""
        self.ids.name_field.text = ""
        self.ids.active_checkbox.active = True
        self._clear_extra_fields()
        self.ids.form_title.text = shape(tr("افزودنِ موردِ تازه"))
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
            self._set_status(tr("کد و نام را وارد کنید."), is_error=True)
            return

        extra = self._collect_extra_fields()
        if self._editing_id is not None:
            try:
                self._update(self._editing_id, company_id, code, name, self.ids.active_checkbox.active, extra)
            except Exception as exc:  # noqa: BLE001 - نمایش هر خطای دیتابیس به کاربر
                self._set_status(tr("خطا: {}").format(exc), is_error=True)
                return
            self.cancel_edit()
            return

        try:
            self._create(company_id, code, name, extra)
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc), is_error=True)
            return
        self.ids.code_field.text = ""
        self.ids.name_field.text = ""
        self._clear_extra_fields()
        self._set_status(tr("مورد افزوده شد."))
        self.refresh_list()

    def confirm_delete(self, detail_account_id: int) -> None:
        row = self._rows_by_id.get(detail_account_id)
        if row is None:
            return
        if self._delete_dialog is not None:
            self._delete_dialog.dismiss()

        def _do_delete(*_args) -> None:
            self._delete_dialog.dismiss()
            self._perform_delete(detail_account_id)

        self._delete_dialog = MDDialog(
            title=shape(tr("حذف")),
            text=shape(tr("«{}» حذف شود؟ این کار قابل بازگشت نیست.").format(row["name"] or row["code"])),
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
            self._delete(detail_account_id, company_id)
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc), is_error=True)
            return
        if self._editing_id == detail_account_id:
            self.cancel_edit()
        else:
            self._set_status(tr("حذف شد."))
            self.refresh_list()


_CUSTOMER_FIELD_SPECS = (
    ("economic_code_field", "economic_code", "text"),
    ("national_id_field", "national_id", "text"),
    ("phone_field", "phone", "text"),
    ("mobile_field", "mobile", "text"),
    ("address_field", "address", "text"),
    ("credit_limit_field", "credit_limit", "decimal"),
    ("notes_field", "notes", "text"),
)

_SUPPLIER_FIELD_SPECS = (
    ("economic_code_field", "economic_code", "text"),
    ("national_id_field", "national_id", "text"),
    ("phone_field", "phone", "text"),
    ("mobile_field", "mobile", "text"),
    ("address_field", "address", "text"),
    ("bank_account_no_field", "bank_account_no", "text"),
    ("notes_field", "notes", "text"),
)

_PERSONNEL_FIELD_SPECS = (
    ("national_id_field", "national_id", "text"),
    ("personnel_no_field", "personnel_no", "text"),
    ("position_title_field", "position_title", "text"),
    ("phone_field", "phone", "text"),
    ("mobile_field", "mobile", "text"),
    ("hire_date_field", "hire_date", "date"),
    ("bank_account_no_field", "bank_account_no", "text"),
    ("notes_field", "notes", "text"),
)


class CustomersScreen(PersonGroupScreenBase):
    FIELD_SPECS = _CUSTOMER_FIELD_SPECS
    EMPTY_ICON = "account-cash-outline"
    EMPTY_TEXT = "هنوز مشتری‌ای تعریف نشده است."

    def _list_rows(self, company_id: int) -> list[dict]:
        return dimensions_service.list_customers(company_id)

    def _create(self, company_id: int, code: str, name: str, extra: dict) -> None:
        dimensions_service.create_customer(company_id=company_id, code=code, name=name, **extra)

    def _update(self, detail_account_id, company_id, code, name, is_active, extra) -> None:
        dimensions_service.update_customer(
            detail_account_id=detail_account_id, company_id=company_id, code=code, name=name, is_active=is_active, **extra
        )

    def _delete(self, detail_account_id: int, company_id: int) -> None:
        dimensions_service.delete_customer(detail_account_id, company_id)


class SuppliersScreen(PersonGroupScreenBase):
    FIELD_SPECS = _SUPPLIER_FIELD_SPECS
    EMPTY_ICON = "truck-outline"
    EMPTY_TEXT = "هنوز تامین‌کننده‌ای تعریف نشده است."

    def _list_rows(self, company_id: int) -> list[dict]:
        return dimensions_service.list_suppliers(company_id)

    def _create(self, company_id: int, code: str, name: str, extra: dict) -> None:
        dimensions_service.create_supplier(company_id=company_id, code=code, name=name, **extra)

    def _update(self, detail_account_id, company_id, code, name, is_active, extra) -> None:
        dimensions_service.update_supplier(
            detail_account_id=detail_account_id, company_id=company_id, code=code, name=name, is_active=is_active, **extra
        )

    def _delete(self, detail_account_id: int, company_id: int) -> None:
        dimensions_service.delete_supplier(detail_account_id, company_id)


class PersonnelScreen(PersonGroupScreenBase):
    FIELD_SPECS = _PERSONNEL_FIELD_SPECS
    EMPTY_ICON = "badge-account-outline"
    EMPTY_TEXT = "هنوز پرسنلی تعریف نشده است."

    def _list_rows(self, company_id: int) -> list[dict]:
        return dimensions_service.list_personnel(company_id)

    def _create(self, company_id: int, code: str, name: str, extra: dict) -> None:
        dimensions_service.create_personnel(company_id=company_id, code=code, name=name, **extra)

    def _update(self, detail_account_id, company_id, code, name, is_active, extra) -> None:
        dimensions_service.update_personnel(
            detail_account_id=detail_account_id, company_id=company_id, code=code, name=name, is_active=is_active, **extra
        )

    def _delete(self, detail_account_id: int, company_id: int) -> None:
        dimensions_service.delete_personnel(detail_account_id, company_id)
