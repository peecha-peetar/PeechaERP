"""صفحه‌ی کدینگ حسابداری — فهرست درختیِ حساب‌ها (گروه/کل/معین) + فرم افزودن
حساب زیر یک والدِ اختیاری."""

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
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen

from peecha import session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import field_labels as field_labels_service
from peecha.ui import numerals, theme
from peecha.ui.i18n import tr
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


class AccountRowWidget(RecycleDataViewBehavior, ButtonBehavior, MDBoxLayout):
    """یک ردیفِ جدولِ کدینگ حسابداری: کد | نام (تورفته بر اساس سطح) | سطح |
    وضعیت | ویرایش | حذف. کلیک روی خودِ ردیف هم مثل دکمه‌ی ویرایش عمل می‌کند.

    طبق تست مستقیم: با فهرستِ BoxLayout+ScrollView قبلی که هر ردیف را با
    add_widget در یک حلقه اضافه می‌کرد، بازسازیِ فهرست با ۵۰۰ حساب ۴۲۲
    ثانیه طول می‌کشید (چون هر add_widget کلِ چیدمانِ فرزندهای قبلی را
    دوباره محاسبه می‌کند — O(n²)). RecycleView این مشکل را با دو کار حل
    می‌کند: (۱) کلِ داده یک‌جا به rv.data داده می‌شود، نه ردیف‌به‌ردیف؛
    (۲) فقط ردیف‌های واقعاً قابل‌مشاهده روی صفحه واقعاً ویجت می‌گیرند."""

    account_id = NumericProperty(0)
    code_text = StringProperty("")
    name_text = StringProperty("")
    level_text = StringProperty("")
    level_badge_color = ListProperty([0, 0, 0, 1])
    status_text = StringProperty("")
    status_badge_color = ListProperty([0, 0, 0, 1])
    zebra = BooleanProperty(False)
    selected = BooleanProperty(False)
    on_edit = ObjectProperty(None)
    on_delete = ObjectProperty(None)

    def on_release(self) -> None:
        if self.on_edit is not None:
            self.on_edit(self.account_id)

    def request_delete(self) -> None:
        if self.on_delete is not None:
            self.on_delete(self.account_id)


Factory.register("AccountRowWidget", cls=AccountRowWidget)


class _DimensionCheckRow(MDBoxLayout):
    label_text = StringProperty("")

    def __init__(self, dimension_type_id: int, **kwargs):
        super().__init__(**kwargs)
        self.dimension_type_id = dimension_type_id


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
        self._dimension_types: list[dimensions_service.DimensionTypeRow] = []
        self._dimension_check_rows: list[_DimensionCheckRow] = []

    def on_pre_enter(self, *args):
        self._set_dropdown_text("nature_button", _NATURE_OPTIONS, self._nature_code)
        self._set_dropdown_text("category_button", _CATEGORY_OPTIONS, self._category_code)
        self._set_dropdown_text("account_type_button", _ACCOUNT_TYPE_OPTIONS, self._account_type_code)
        self.apply_field_labels()
        self._build_dimension_checklist(selected_ids=[])
        self.refresh_list()
        self._select_parent(self._parent_account_id)
        self.bind_shortcuts()

    def _build_dimension_checklist(self, selected_ids: list[int]) -> None:
        self.ids.dimension_types_box.clear_widgets()
        self._dimension_check_rows = []
        company_id = session.current_company.company_id if session.current_company else None
        self._dimension_types = dimensions_service.list_active_dimension_types(company_id) if company_id else []
        if not self._dimension_types:
            self.ids.dimension_types_section.opacity = 0
            self.ids.dimension_types_section.disabled = True
            return
        self.ids.dimension_types_section.opacity = 1
        self.ids.dimension_types_section.disabled = False
        for dim in self._dimension_types:
            row = _DimensionCheckRow(dimension_type_id=dim.dimension_type_id, label_text=shape(dim.code))
            row.ids.check.active = dim.dimension_type_id in selected_ids
            self.ids.dimension_types_box.add_widget(row)
            self._dimension_check_rows.append(row)

    def _selected_dimension_type_ids(self) -> list[int]:
        return [row.dimension_type_id for row in self._dimension_check_rows if row.ids.check.active]

    def on_leave(self, *args):
        self.unbind_shortcuts()

    def apply_field_labels(self) -> None:
        language_id = session.current_language.language_id if session.current_language else None
        labels = {k: tr(v) for k, v in field_labels_service.get_labels_map("chart_of_accounts", language_id).items()}
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
        self.ids[button_id].text = shape(tr(label))

    def _open_dropdown(self, button_id: str, options: list[tuple[str, str]], on_select) -> None:
        from peecha.ui.widgets import open_rtl_dropdown  # noqa: PLC0415

        caller = self.ids[button_id]
        items = [
            {"text": shape(tr(label)), "on_release": lambda value=value: (menu.dismiss(), on_select(value))}
            for value, label in options
        ]
        menu = open_rtl_dropdown(caller, items, width_mult=4)
        self._menus[button_id] = menu

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
        from peecha.ui.widgets import open_rtl_dropdown  # noqa: PLC0415

        caller = self.ids.parent_button
        items = [
            {
                "text": shape(tr(_NO_PARENT_LABEL)),
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
        menu = open_rtl_dropdown(caller, items, width_mult=4)
        self._menus["parent_button"] = menu

    def _select_parent(self, account_id: int | None) -> None:
        self._parent_account_id = account_id
        if account_id is None:
            self.ids.parent_button.text = shape(tr(_NO_PARENT_LABEL))
            self.ids.level_preview_label.text = shape(f"{tr('سطحِ حساب جدید:')} {tr(_LEVEL_LABELS[1])}")
            return
        parent = next(row for row in self._parent_options if row.account_id == account_id)
        self.ids.parent_button.text = shape(f"{numerals.to_persian_digits(parent.full_code)} — {parent.name}")
        new_level = parent.account_level + 1
        self.ids.level_preview_label.text = shape(f"{tr('سطحِ حساب جدید:')} {tr(_LEVEL_LABELS[new_level])}")

    def _set_status(self, message: str) -> None:
        self.ids.status_label.text = shape(message)

    def refresh_list(self) -> None:
        if session.current_company is None:
            self._set_status(tr("هیچ شرکتی انتخاب نشده است."))
            self.ids.grid_header.opacity = 0
            self.ids.accounts_list.data = []
            return

        rows = coa_service.list_accounts(session.current_company.company_id)
        self._parent_options = rows
        self._accounts_by_id = {row.account_id: row for row in rows}
        self._set_status(tr(""))
        self.ids.grid_header.opacity = 1 if rows else 0

        if not rows:
            self.ids.accounts_list.data = [
                {
                    "viewclass": "PEmptyState",
                    "icon": "format-list-bulleted-square",
                    "text": shape(tr("هنوز حسابی تعریف نشده — از فرم روبه‌رو یک حساب گروه اضافه کنید.")),
                }
            ]
        else:
            self.ids.accounts_list.data = [
                {
                    "account_id": row.account_id,
                    "on_edit": self.edit_account,
                    "on_delete": self.confirm_delete,
                    "code_text": numerals.to_persian_digits(row.full_code),
                    "name_text": shape(f"{'    ' * (row.account_level - 1)}{row.name}"),
                    "level_text": shape(tr(_LEVEL_LABELS[row.account_level])),
                    "level_badge_color": _LEVEL_BADGE_COLORS[row.account_level],
                    "status_text": shape(tr("قابل ثبت") if row.is_postable else tr("گروه‌بندی")),
                    "status_badge_color": theme.SUCCESS if row.is_postable else theme.TEXT_DISABLED,
                    "zebra": i % 2 == 1,
                    "selected": row.account_id == self._editing_account_id,
                }
                for i, row in enumerate(rows)
            ]

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
        self.ids.segment_code_field.set_value(row.full_code.rsplit("-", 1)[-1])
        self.ids.segment_code_field.disabled = True
        self.ids.parent_button.disabled = True
        self.ids.name_field.set_value(row.name)
        self.ids.name_field.focus = True
        self._nature_code = row.nature_code
        self._category_code = row.category_code
        self._account_type_code = row.account_type_code
        self.ids.is_postable_checkbox.active = row.is_postable
        self._set_dropdown_text("nature_button", _NATURE_OPTIONS, self._nature_code)
        self._set_dropdown_text("category_button", _CATEGORY_OPTIONS, self._category_code)
        self._set_dropdown_text("account_type_button", _ACCOUNT_TYPE_OPTIONS, self._account_type_code)
        self.ids.form_title.text = shape(tr("ویرایش حساب «{}»").format(numerals.to_persian_digits(row.full_code)))
        self.ids.save_button.text = shape(tr("ذخیره تغییرات"))
        self.ids.cancel_edit_button.opacity = 1
        self.ids.cancel_edit_button.disabled = False
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "36dp"
        self._set_status(
            tr("در حال ویرایش «{}» — Escape برای لغو.").format(f"{numerals.to_persian_digits(row.full_code)} — {row.name}")
        )
        self._build_dimension_checklist(selected_ids=dimensions_service.get_account_dimension_type_ids(account_id))
        self.refresh_list()

    def cancel_edit(self) -> None:
        self._editing_account_id = None
        self.ids.segment_code_field.text = ""
        self.ids.segment_code_field.disabled = False
        self.ids.parent_button.disabled = False
        self.ids.name_field.text = ""
        self.ids.form_title.text = shape(tr("افزودن حساب جدید"))
        self.ids.save_button.text = shape(tr("افزودن حساب"))
        self.ids.cancel_edit_button.opacity = 0
        self.ids.cancel_edit_button.disabled = True
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "0dp"
        self._set_status(tr(""))
        self._build_dimension_checklist(selected_ids=[])
        self.refresh_list()

    def save_account(self) -> None:
        if session.current_company is None:
            self._set_status(tr("هیچ شرکتی انتخاب نشده است."))
            return

        name = self.ids.name_field.value.strip()
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
                self._set_status(tr("نام حساب را وارد کنید."))
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
                    changed_by_user_id=session.current_user.user_id if session.current_user else None,
                )
                dimensions_service.set_account_dimension_types(
                    account_id=self._editing_account_id,
                    company_id=session.current_company.company_id,
                    dimension_type_ids=self._selected_dimension_type_ids(),
                )
            except Exception as exc:  # noqa: BLE001 - نمایش هر خطای دیتابیس به کاربر
                self._set_status(tr("خطا: {}").format(exc))
                return
            self.cancel_edit()
            return

        # کد حساب فارسی نمایش داده می‌شود (persian_digits: True در KV) اما
        # باید همیشه ASCII ذخیره شود — چون full_code برای مرتب‌سازی/تطبیقِ
        # والد استفاده می‌شود و مخلوط‌شدنِ دو سیستمِ رقمی آن را می‌شکند.
        segment_code = numerals.to_ascii_digits(self.ids.segment_code_field.value.strip())
        if not segment_code or not name:
            self._set_status(tr("کد و نام حساب را وارد کنید."))
            return
        try:
            account = coa_service.create_account(
                company_id=session.current_company.company_id,
                segment_code=segment_code,
                name=name,
                nature_code=self._nature_code,
                category_code=self._category_code,
                account_type_code=self._account_type_code,
                is_postable=self.ids.is_postable_checkbox.active,
                language_id=language_id,
                parent_account_id=self._parent_account_id,
                changed_by_user_id=session.current_user.user_id if session.current_user else None,
            )
            dimensions_service.set_account_dimension_types(
                account_id=account.account_id,
                company_id=session.current_company.company_id,
                dimension_type_ids=self._selected_dimension_type_ids(),
            )
        except Exception as exc:  # noqa: BLE001 - نمایش هر خطای دیتابیس به کاربر
            self._set_status(tr("خطا: {}").format(exc))
            return

        self.ids.segment_code_field.text = ""
        self.ids.name_field.text = ""
        self._build_dimension_checklist(selected_ids=[])
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
            title=shape(tr("حذف حساب")),
            text=shape(
                tr("حساب «{}» حذف شود؟ این کار قابل بازگشت نیست.").format(
                    f"{numerals.to_persian_digits(row.full_code)} — {row.name}"
                )
            ),
            buttons=[
                MDFlatButton(text=shape(tr("لغو")), on_release=lambda *_: self._delete_dialog.dismiss()),
                MDRaisedButton(text=shape(tr("حذف")), md_bg_color=theme.DANGER, on_release=_do_delete),
            ],
        )
        self._delete_dialog.open()

    def _perform_delete(self, account_id: int) -> None:
        if session.current_company is None:
            return
        try:
            coa_service.delete_account(
                account_id,
                session.current_company.company_id,
                changed_by_user_id=session.current_user.user_id if session.current_user else None,
            )
        except Exception as exc:  # noqa: BLE001 - نمایش هر خطای دیتابیس به کاربر
            self._set_status(tr("خطا: {}").format(exc))
            return
        if self._editing_account_id == account_id:
            self.cancel_edit()
        else:
            self._set_status(tr("حساب حذف شد."))
            self.refresh_list()
