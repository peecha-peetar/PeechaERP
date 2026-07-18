"""صفحه‌ی کدینگ حسابداری — فهرست حساب‌های شرکت جاری + فرم افزودن حساب گروه."""

from __future__ import annotations

import os

from kivy.lang import Builder
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen

from peecha import session
from peecha.services import chart_of_accounts as coa_service
from peecha.ui.rtl import shape

_KV_PATH = os.path.join(os.path.dirname(__file__), "chart_of_accounts.kv")
Builder.load_file(_KV_PATH)

_NATURE_OPTIONS = [("DEBIT", "بدهکار"), ("CREDIT", "بستانکار"), ("BOTH", "دوطرفه")]
_CATEGORY_OPTIONS = [
    ("ASSET", "دارایی"), ("LIABILITY", "بدهی"), ("EQUITY", "حقوق صاحبان سهام"),
    ("REVENUE", "درآمد"), ("EXPENSE", "هزینه"),
]
_ACCOUNT_TYPE_OPTIONS = [("PERMANENT", "ترازنامه‌ای"), ("TEMPORARY", "موقت")]


class ChartOfAccountsScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._nature_code = _NATURE_OPTIONS[0][0]
        self._category_code = _CATEGORY_OPTIONS[0][0]
        self._account_type_code = _ACCOUNT_TYPE_OPTIONS[0][0]
        self._menus: dict[str, MDDropdownMenu] = {}

    def on_pre_enter(self, *args):
        self._set_dropdown_text("nature_button", _NATURE_OPTIONS, self._nature_code)
        self._set_dropdown_text("category_button", _CATEGORY_OPTIONS, self._category_code)
        self._set_dropdown_text("account_type_button", _ACCOUNT_TYPE_OPTIONS, self._account_type_code)
        self.refresh_list()

    def _set_dropdown_text(self, button_id: str, options: list[tuple[str, str]], code: str) -> None:
        label = next(label for value, label in options if value == code)
        self.ids[button_id].text = shape(label)

    def _open_dropdown(self, button_id: str, options: list[tuple[str, str]], on_select) -> None:
        caller = self.ids[button_id]
        items = [
            {"text": shape(label), "on_release": lambda value=value: (menu.dismiss(), on_select(value))}
            for value, label in options
        ]
        menu = MDDropdownMenu(caller=caller, items=items, width_mult=4)
        self._menus[button_id] = menu
        menu.open()

    def open_nature_menu(self) -> None:
        def select(value: str) -> None:
            self._nature_code = value
            self._set_dropdown_text("nature_button", _NATURE_OPTIONS, value)

        self._open_dropdown("nature_button", _NATURE_OPTIONS, select)

    def open_category_menu(self) -> None:
        def select(value: str) -> None:
            self._category_code = value
            self._set_dropdown_text("category_button", _CATEGORY_OPTIONS, value)

        self._open_dropdown("category_button", _CATEGORY_OPTIONS, select)

    def open_account_type_menu(self) -> None:
        def select(value: str) -> None:
            self._account_type_code = value
            self._set_dropdown_text("account_type_button", _ACCOUNT_TYPE_OPTIONS, value)

        self._open_dropdown("account_type_button", _ACCOUNT_TYPE_OPTIONS, select)

    def _set_status(self, message: str) -> None:
        self.ids.status_label.text = shape(message)

    def refresh_list(self) -> None:
        self.ids.accounts_list.clear_widgets()
        if session.current_company is None:
            self._set_status("هیچ شرکتی انتخاب نشده است.")
            return

        from peecha.ui.widgets import PLabelListRow  # noqa: PLC0415

        rows = coa_service.list_accounts(session.current_company.company_id)
        if not rows:
            self._set_status("هنوز حسابی تعریف نشده — از فرم روبه‌رو یک حساب گروه اضافه کنید.")
        else:
            self._set_status("")
        for row in rows:
            indent = "    " * (row.account_level - 1)
            text = f"{row.full_code}   {indent}{row.name}"
            self.ids.accounts_list.add_widget(PLabelListRow(text=shape(text)))

    def add_account(self) -> None:
        if session.current_company is None:
            self._set_status("هیچ شرکتی انتخاب نشده است.")
            return

        segment_code = self.ids.segment_code_field.text.strip()
        name = self.ids.name_field.text.strip()
        if not segment_code or not name:
            self._set_status("کد و نام حساب را وارد کنید.")
            return

        language_id = (
            session.current_user.default_language_id
            if session.current_user and session.current_user.default_language_id
            else session.current_company.default_language_id
        )
        try:
            coa_service.create_root_account(
                company_id=session.current_company.company_id,
                segment_code=segment_code,
                name=name,
                nature_code=self._nature_code,
                category_code=self._category_code,
                account_type_code=self._account_type_code,
                is_postable=self.ids.is_postable_checkbox.active,
                language_id=language_id,
            )
        except Exception as exc:  # noqa: BLE001 - نمایش هر خطای دیتابیس به کاربر
            self._set_status(f"خطا: {exc}")
            return

        self.ids.segment_code_field.text = ""
        self.ids.name_field.text = ""
        self.refresh_list()
