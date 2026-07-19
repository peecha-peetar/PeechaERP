"""صفحه‌ی کدینگ حسابداری — فهرست درختیِ حساب‌ها (گروه/کل/معین) + فرم افزودن
حساب زیر یک والدِ اختیاری."""

from __future__ import annotations

import os

from kivy.lang import Builder
from kivy.properties import BooleanProperty, ListProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen

from peecha import session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import field_labels as field_labels_service
from peecha.ui import numerals, theme
from peecha.ui.rtl import shape
from peecha.ui.shortcuts import KeyboardShortcutMixin

_KV_PATH = os.path.join(os.path.dirname(__file__), "chart_of_accounts.kv")
Builder.load_file(_KV_PATH)

_NATURE_OPTIONS = [("DEBIT", "بدهکار"), ("CREDIT", "بستانکار"), ("BOTH", "دوطرفه")]
_CATEGORY_OPTIONS = [
    ("ASSET", "دارایی"), ("LIABILITY", "بدهی"), ("EQUITY", "حقوق صاحبان سهام"),
    ("REVENUE", "درآمد"), ("EXPENSE", "هزینه"),
]
_ACCOUNT_TYPE_OPTIONS = [("PERMANENT", "ترازنامه‌ای"), ("TEMPORARY", "موقت")]
_LEVEL_LABELS = {1: "گروه", 2: "کل", 3: "معین"}
_LEVEL_BADGE_COLORS = {1: theme.TEXT_SECONDARY, 2: theme.INFO, 3: theme.ACCENT}
_NO_PARENT_LABEL = "— بدون والد (سطح گروه) —"


class AccountRowWidget(ButtonBehavior, MDBoxLayout):
    """یک ردیفِ جدولِ کدینگ حسابداری: کد | نام (تورفته بر اساس سطح) | سطح |
    وضعیت | ویرایش | حذف. کلیک روی خودِ ردیف هم مثل دکمه‌ی ویرایش عمل می‌کند."""

    code_text = StringProperty("")
    name_text = StringProperty("")
    level_text = StringProperty("")
    level_badge_color = ListProperty([0, 0, 0, 1])
    status_text = StringProperty("")
    status_badge_color = ListProperty([0, 0, 0, 1])
    zebra = BooleanProperty(False)
    selected = BooleanProperty(False)

    def __init__(self, account_id: int, on_edit, on_delete, **kwargs):
        super().__init__(**kwargs)
        self.account_id = account_id
        self._on_edit = on_edit
        self._on_delete = on_delete

    def on_release(self) -> None:
        self._on_edit(self.account_id)

    def request_delete(self) -> None:
        self._on_delete(self.account_id)


class ChartOfAccountsScreen(KeyboardShortcutMixin, MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._nature_code = _NATURE_OPTIONS[0][0]
        self._category_code = _CATEGORY_OPTIONS[0][0]
        self._account_type_code = _ACCOUNT_TYPE_OPTIONS[0][0]
        self._parent_account_id: int | None = None
        self._parent_options: list[coa_service.AccountRow] = []
        self._accounts_by_id: dict[int, coa_service.AccountRow] = {}
        self._menus: dict[str, MDDropdownMenu] = {}
        self._editing_account_id: int | None = None
        self._delete_dialog: MDDialog | None = None

    def on_pre_enter(self, *args):
        self._set_dropdown_text("nature_button", _NATURE_OPTIONS, self._nature_code)
        self._set_dropdown_text("category_button", _CATEGORY_OPTIONS, self._category_code)
        self._set_dropdown_text("account_type_button", _ACCOUNT_TYPE_OPTIONS, self._account_type_code)
        self.apply_field_labels()
        self.refresh_list()
        self._select_parent(self._parent_account_id)
        self.bind_shortcuts()

    def on_leave(self, *args):
        self.unbind_shortcuts()

    def apply_field_labels(self) -> None:
        language_id = session.current_language.language_id if session.current_language else None
        labels = field_labels_service.get_labels_map("chart_of_accounts", language_id)
        self.ids.segment_code_field.hint_text = shape(labels["segment_code"])
        self.ids.name_field.hint_text = shape(labels["name"])

    def on_shortcut_save(self) -> None:
        self.save_account()

    def on_shortcut_cancel(self) -> bool:
        if self._editing_account_id is not None:
            self.cancel_edit()
            return True
        return False

    def on_shortcut_delete(self) -> bool:
        if self._editing_account_id is not None:
            self.confirm_delete(self._editing_account_id)
            return True
        return False

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

    def open_parent_menu(self) -> None:
        caller = self.ids.parent_button
        items = [
            {
                "text": shape(_NO_PARENT_LABEL),
                "on_release": lambda: (menu.dismiss(), self._select_parent(None)),
            }
        ]
        for row in self._parent_options:
            if row.account_level >= coa_service.MAX_ACCOUNT_LEVEL:
                continue  # معین دیگر نمی‌تواند زیرشاخه بگیرد
            label = f"{numerals.to_persian_digits(row.full_code)} — {row.name}"
            items.append(
                {
                    "text": shape(label),
                    "on_release": lambda account_id=row.account_id: (menu.dismiss(), self._select_parent(account_id)),
                }
            )
        menu = MDDropdownMenu(caller=caller, items=items, width_mult=4)
        self._menus["parent_button"] = menu
        menu.open()

    def _select_parent(self, account_id: int | None) -> None:
        self._parent_account_id = account_id
        if account_id is None:
            self.ids.parent_button.text = shape(_NO_PARENT_LABEL)
            self.ids.level_preview_label.text = shape(f"سطحِ حساب جدید: {_LEVEL_LABELS[1]}")
            return
        parent = next(row for row in self._parent_options if row.account_id == account_id)
        self.ids.parent_button.text = shape(f"{numerals.to_persian_digits(parent.full_code)} — {parent.name}")
        new_level = parent.account_level + 1
        self.ids.level_preview_label.text = shape(f"سطحِ حساب جدید: {_LEVEL_LABELS[new_level]}")

    def _set_status(self, message: str) -> None:
        self.ids.status_label.text = shape(message)

    def refresh_list(self) -> None:
        self.ids.accounts_list.clear_widgets()
        if session.current_company is None:
            self._set_status("هیچ شرکتی انتخاب نشده است.")
            self.ids.grid_header.opacity = 0
            return

        from peecha.ui.widgets import PEmptyState  # noqa: PLC0415

        rows = coa_service.list_accounts(session.current_company.company_id)
        self._parent_options = rows
        self._accounts_by_id = {row.account_id: row for row in rows}
        self._set_status("")
        self.ids.grid_header.opacity = 1 if rows else 0
        if not rows:
            self.ids.accounts_list.add_widget(
                PEmptyState(
                    icon="format-list-bulleted-square",
                    text=shape("هنوز حسابی تعریف نشده — از فرم روبه‌رو یک حساب گروه اضافه کنید."),
                )
            )
        for i, row in enumerate(rows):
            indent = "    " * (row.account_level - 1)
            self.ids.accounts_list.add_widget(
                AccountRowWidget(
                    account_id=row.account_id,
                    on_edit=self.edit_account,
                    on_delete=self.confirm_delete,
                    code_text=numerals.to_persian_digits(row.full_code),
                    name_text=shape(f"{indent}{row.name}"),
                    level_text=shape(_LEVEL_LABELS[row.account_level]),
                    level_badge_color=_LEVEL_BADGE_COLORS[row.account_level],
                    status_text=shape("قابل ثبت" if row.is_postable else "گروه‌بندی"),
                    status_badge_color=theme.SUCCESS if row.is_postable else theme.TEXT_DISABLED,
                    zebra=i % 2 == 1,
                    selected=row.account_id == self._editing_account_id,
                )
            )

        # اگر والدِ انتخاب‌شده دیگر معتبر نیست (مثلاً بعد از رفرش) بازنشانی می‌شود
        if self._parent_account_id is not None and not any(
            r.account_id == self._parent_account_id for r in rows
        ):
            self._select_parent(None)

        if self._editing_account_id is not None and self._editing_account_id not in self._accounts_by_id:
            self.cancel_edit()

    def edit_account(self, account_id: int) -> None:
        row = self._accounts_by_id.get(account_id)
        if row is None:
            return
        self._editing_account_id = account_id
        self.ids.segment_code_field.text = row.full_code.rsplit("-", 1)[-1]
        self.ids.segment_code_field.disabled = True
        self.ids.parent_button.disabled = True
        self.ids.name_field.text = row.name
        self.ids.name_field.focus = True
        self._nature_code = row.nature_code
        self._category_code = row.category_code
        self._account_type_code = row.account_type_code
        self.ids.is_postable_checkbox.active = row.is_postable
        self._set_dropdown_text("nature_button", _NATURE_OPTIONS, self._nature_code)
        self._set_dropdown_text("category_button", _CATEGORY_OPTIONS, self._category_code)
        self._set_dropdown_text("account_type_button", _ACCOUNT_TYPE_OPTIONS, self._account_type_code)
        self.ids.form_title.text = shape(f"ویرایش حساب «{numerals.to_persian_digits(row.full_code)}»")
        self.ids.save_button.text = shape("ذخیره تغییرات")
        self.ids.cancel_edit_button.opacity = 1
        self.ids.cancel_edit_button.disabled = False
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "36dp"
        self._set_status(
            f"در حال ویرایش «{numerals.to_persian_digits(row.full_code)} — {row.name}» — Escape برای لغو."
        )
        self.refresh_list()

    def cancel_edit(self) -> None:
        self._editing_account_id = None
        self.ids.segment_code_field.text = ""
        self.ids.segment_code_field.disabled = False
        self.ids.parent_button.disabled = False
        self.ids.name_field.text = ""
        self.ids.form_title.text = shape("افزودن حساب جدید")
        self.ids.save_button.text = shape("افزودن حساب")
        self.ids.cancel_edit_button.opacity = 0
        self.ids.cancel_edit_button.disabled = True
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "0dp"
        self._set_status("")
        self.refresh_list()

    def save_account(self) -> None:
        if session.current_company is None:
            self._set_status("هیچ شرکتی انتخاب نشده است.")
            return

        name = self.ids.name_field.text.strip()
        # اولویت با زبانِ فعالِ انتخاب‌شده در سوییچرِ هدر است (طبق درخواستِ
        # صریح)، بعد زبانِ پیش‌فرضِ کاربر، بعد زبانِ پیش‌فرضِ شرکت.
        language_id = (
            session.current_language.language_id
            if session.current_language
            else (
                session.current_user.default_language_id
                if session.current_user and session.current_user.default_language_id
                else session.current_company.default_language_id
            )
        )

        if self._editing_account_id is not None:
            if not name:
                self._set_status("نام حساب را وارد کنید.")
                return
            try:
                coa_service.update_account(
                    account_id=self._editing_account_id,
                    company_id=session.current_company.company_id,
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
            self.cancel_edit()
            return

        # کد حساب فارسی نمایش داده می‌شود (persian_digits: True در KV) اما
        # باید همیشه ASCII ذخیره شود — چون full_code برای مرتب‌سازی/تطبیقِ
        # والد استفاده می‌شود و مخلوط‌شدنِ دو سیستمِ رقمی آن را می‌شکند.
        segment_code = numerals.to_ascii_digits(self.ids.segment_code_field.text.strip())
        if not segment_code or not name:
            self._set_status("کد و نام حساب را وارد کنید.")
            return
        try:
            coa_service.create_account(
                company_id=session.current_company.company_id,
                segment_code=segment_code,
                name=name,
                nature_code=self._nature_code,
                category_code=self._category_code,
                account_type_code=self._account_type_code,
                is_postable=self.ids.is_postable_checkbox.active,
                language_id=language_id,
                parent_account_id=self._parent_account_id,
            )
        except Exception as exc:  # noqa: BLE001 - نمایش هر خطای دیتابیس به کاربر
            self._set_status(f"خطا: {exc}")
            return

        self.ids.segment_code_field.text = ""
        self.ids.name_field.text = ""
        self.refresh_list()

    def confirm_delete(self, account_id: int) -> None:
        row = self._accounts_by_id.get(account_id)
        if row is None:
            return

        if self._delete_dialog is not None:
            self._delete_dialog.dismiss()

        def _do_delete(*_args) -> None:
            self._delete_dialog.dismiss()
            self._perform_delete(account_id)

        self._delete_dialog = MDDialog(
            title=shape("حذف حساب"),
            text=shape(
                f"حساب «{numerals.to_persian_digits(row.full_code)} — {row.name}» حذف شود؟ این کار قابل بازگشت نیست."
            ),
            buttons=[
                MDFlatButton(text=shape("لغو"), on_release=lambda *_: self._delete_dialog.dismiss()),
                MDRaisedButton(text=shape("حذف"), md_bg_color=theme.DANGER, on_release=_do_delete),
            ],
        )
        self._delete_dialog.open()

    def _perform_delete(self, account_id: int) -> None:
        if session.current_company is None:
            return
        try:
            coa_service.delete_account(account_id, session.current_company.company_id)
        except Exception as exc:  # noqa: BLE001 - نمایش هر خطای دیتابیس به کاربر
            self._set_status(f"خطا: {exc}")
            return
        if self._editing_account_id == account_id:
            self.cancel_edit()
        else:
            self._set_status("حساب حذف شد.")
            self.refresh_list()
