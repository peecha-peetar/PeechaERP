"""صفحه‌ی مدیریت شرکت‌ها — تعریفِ شرکت‌های سیستم (چندشرکتی)، هرکدام با
ارزِ پایه و زبانِ پیش‌فرضِ خودشان."""

from __future__ import annotations

import os

from kivy.lang import Builder
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen

from peecha import session
from peecha.services import companies as companies_service
from peecha.services import field_labels as field_labels_service
from peecha.services import languages as languages_service
from peecha.ui import numerals, theme
from peecha.ui.i18n import tr
from peecha.ui.rtl import shape
from peecha.ui.shortcuts import KeyboardShortcutMixin

_KV_PATH = os.path.join(os.path.dirname(__file__), "companies.kv")
Builder.load_file(_KV_PATH)


class CompanyRowWidget(ButtonBehavior, MDBoxLayout):
    code_text = StringProperty("")
    name_text = StringProperty("")
    currency_text = StringProperty("")
    language_text = StringProperty("")
    status_text = StringProperty("")
    is_active_row = BooleanProperty(True)
    zebra = BooleanProperty(False)
    selected = BooleanProperty(False)

    def __init__(self, company_id: int, on_edit, **kwargs):
        super().__init__(**kwargs)
        self.company_id = company_id
        self._on_edit = on_edit

    def on_release(self) -> None:
        self._on_edit(self.company_id)


class CompaniesScreen(KeyboardShortcutMixin, MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._rows_by_id: dict[int, companies_service.CompanyRow] = {}
        self._currency_options: list[companies_service.CurrencyOption] = []
        self._language_options: list[languages_service.LanguageRow] = []
        self._currency_id: int | None = None
        self._language_id: int | None = None
        self._editing_company_id: int | None = None
        self._menus: dict[str, MDDropdownMenu] = {}

    def on_pre_enter(self, *args):
        self._currency_options = companies_service.list_currencies()
        self._language_options = languages_service.list_languages()
        if self._currency_id is None and self._currency_options:
            self._currency_id = self._currency_options[0].currency_id
        if self._language_id is None and self._language_options:
            default_lang = next((l for l in self._language_options if l.is_default), self._language_options[0])
            self._language_id = default_lang.language_id
        self._refresh_dropdown_texts()
        self.apply_field_labels()
        self.refresh_list()
        self.bind_shortcuts()

    def on_leave(self, *args):
        self.unbind_shortcuts()

    def apply_field_labels(self) -> None:
        language_id = session.current_language.language_id if session.current_language else None
        labels = {k: tr(v) for k, v in field_labels_service.get_labels_map("companies", language_id).items()}
        self.ids.code_field.hint_text = shape(labels["code"])
        self.ids.legal_name_field.hint_text = shape(labels["legal_name"])
        self.ids.display_name_field.hint_text = shape(labels["display_name"])
        self.ids.economic_code_field.hint_text = shape(labels["economic_code"])
        self.ids.registration_no_field.hint_text = shape(labels["registration_no"])
        self.ids.national_id_field.hint_text = shape(labels["national_id"])
        self.ids.fy_start_day_field.hint_text = shape(labels["fy_start_day"])
        self.ids.fy_start_month_field.hint_text = shape(labels["fy_start_month"])

    def on_shortcut_save(self) -> None:
        self.save_company()

    def on_shortcut_cancel(self) -> bool:
        if self._editing_company_id is not None:
            self.cancel_edit()
            return True
        return False

    def _refresh_dropdown_texts(self) -> None:
        currency = next((c for c in self._currency_options if c.currency_id == self._currency_id), None)
        self.ids.currency_button.text = shape(currency.iso_code if currency else "— انتخاب ارز —")
        self.ids.currency_decimals_field.text = (
            numerals.to_persian_digits(str(currency.decimal_places)) if currency else ""
        )
        language = next((l for l in self._language_options if l.language_id == self._language_id), None)
        self.ids.language_button.text = shape(language.native_name if language else "— انتخاب زبان —")

    def save_currency_decimals(self) -> None:
        if self._currency_id is None:
            return
        raw = numerals.to_ascii_digits(self.ids.currency_decimals_field.text).strip()
        try:
            decimal_places = int(raw)
            companies_service.update_currency_decimal_places(self._currency_id, decimal_places)
        except ValueError as exc:
            self._set_status(str(exc))
            return
        self._currency_options = companies_service.list_currencies()
        self._refresh_dropdown_texts()
        self._set_status("رقم اعشارِ ارز ذخیره شد.")

    def open_currency_menu(self) -> None:
        from peecha.ui.widgets import open_rtl_dropdown  # noqa: PLC0415

        items = [
            {
                "text": shape(c.iso_code),
                "on_release": lambda cid=c.currency_id: (menu.dismiss(), self._select_currency(cid)),
            }
            for c in self._currency_options
        ]
        menu = open_rtl_dropdown(self.ids.currency_button, items, width_mult=3)
        self._menus["currency"] = menu

    def _select_currency(self, currency_id: int) -> None:
        self._currency_id = currency_id
        self._refresh_dropdown_texts()

    def open_language_menu(self) -> None:
        from peecha.ui.widgets import open_rtl_dropdown  # noqa: PLC0415

        items = [
            {
                "text": shape(l.native_name),
                "on_release": lambda lid=l.language_id: (menu.dismiss(), self._select_language(lid)),
            }
            for l in self._language_options
        ]
        menu = open_rtl_dropdown(self.ids.language_button, items, width_mult=3)
        self._menus["language"] = menu

    def _select_language(self, language_id: int) -> None:
        self._language_id = language_id
        self._refresh_dropdown_texts()

    def _set_status(self, message: str) -> None:
        self.ids.status_label.text = shape(message)

    def refresh_list(self) -> None:
        self.ids.companies_list.clear_widgets()
        from peecha.ui.widgets import PEmptyState  # noqa: PLC0415

        rows = companies_service.list_companies()
        self._rows_by_id = {r.company_id: r for r in rows}
        self.ids.grid_header.opacity = 1 if rows else 0
        if not rows:
            self.ids.companies_list.add_widget(
                PEmptyState(icon="domain", text=shape(tr("هنوز شرکتی تعریف نشده است.")))
            )
        for i, row in enumerate(rows):
            self.ids.companies_list.add_widget(
                CompanyRowWidget(
                    company_id=row.company_id,
                    on_edit=self.edit_company,
                    code_text=row.code,
                    name_text=shape(row.display_name),
                    currency_text=row.base_currency_code,
                    language_text=shape(row.default_language_name),
                    status_text=shape(tr("فعال") if row.is_active else tr("غیرفعال")),
                    is_active_row=row.is_active,
                    zebra=i % 2 == 1,
                    selected=row.company_id == self._editing_company_id,
                )
            )

    def edit_company(self, company_id: int) -> None:
        row = self._rows_by_id.get(company_id)
        if row is None:
            return
        self._editing_company_id = company_id
        self.ids.code_field.set_value(row.code)
        self.ids.code_field.disabled = True
        self.ids.legal_name_field.set_value(row.legal_name)
        self.ids.display_name_field.set_value(row.display_name)
        self.ids.display_name_field.focus = True
        self.ids.economic_code_field.set_value(row.economic_code or "")
        self.ids.registration_no_field.set_value(row.registration_no or "")
        self.ids.national_id_field.set_value(row.national_id or "")
        self.ids.fy_start_month_field.text = numerals.to_persian_digits(str(row.fiscal_year_start_month))
        self.ids.fy_start_day_field.text = numerals.to_persian_digits(str(row.fiscal_year_start_day))
        self._currency_id = row.base_currency_id
        self._language_id = row.default_language_id
        self._refresh_dropdown_texts()
        self.ids.is_active_checkbox.active = row.is_active
        self.ids.form_title.text = shape(tr("ویرایش شرکت «{}»").format(row.display_name))
        self.ids.save_button.text = shape(tr("ذخیره تغییرات"))
        self.ids.cancel_edit_button.opacity = 1
        self.ids.cancel_edit_button.disabled = False
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "36dp"
        self._set_status(tr("در حال ویرایش «{}» — Escape برای لغو.").format(row.display_name))
        self.refresh_list()

    def cancel_edit(self) -> None:
        self._editing_company_id = None
        self.ids.code_field.text = ""
        self.ids.code_field.disabled = False
        self.ids.legal_name_field.text = ""
        self.ids.display_name_field.text = ""
        self.ids.economic_code_field.text = ""
        self.ids.registration_no_field.text = ""
        self.ids.national_id_field.text = ""
        self.ids.fy_start_month_field.text = "۱"
        self.ids.fy_start_day_field.text = "۱"
        self.ids.is_active_checkbox.active = True
        self.ids.form_title.text = shape(tr("افزودن شرکت جدید"))
        self.ids.save_button.text = shape(tr("افزودن شرکت"))
        self.ids.cancel_edit_button.opacity = 0
        self.ids.cancel_edit_button.disabled = True
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "0dp"
        self._set_status("")
        self.refresh_list()

    def save_company(self) -> None:
        legal_name = self.ids.legal_name_field.value.strip()
        display_name = self.ids.display_name_field.value.strip()
        if self._currency_id is None or self._language_id is None:
            self._set_status("ابتدا یک ارزِ پایه و زبانِ پیش‌فرض تعریف کنید.")
            return
        try:
            fy_month = int(numerals.to_ascii_digits(self.ids.fy_start_month_field.text.strip()) or "1")
            fy_day = int(numerals.to_ascii_digits(self.ids.fy_start_day_field.text.strip()) or "1")
        except ValueError:
            self._set_status("ماه/روزِ شروعِ سال مالی نامعتبر است.")
            return
        if not (1 <= fy_month <= 12) or not (1 <= fy_day <= 31):
            self._set_status("ماه باید بین ۱ تا ۱۲ و روز باید بین ۱ تا ۳۱ باشد.")
            return

        if self._editing_company_id is not None:
            if not legal_name or not display_name:
                self._set_status("نام حقوقی و نام نمایشی را وارد کنید.")
                return
            try:
                companies_service.update_company(
                    company_id=self._editing_company_id,
                    legal_name=legal_name,
                    display_name=display_name,
                    base_currency_id=self._currency_id,
                    default_language_id=self._language_id,
                    fiscal_year_start_month=fy_month,
                    fiscal_year_start_day=fy_day,
                    is_active=self.ids.is_active_checkbox.active,
                    economic_code=self.ids.economic_code_field.value.strip(),
                    registration_no=self.ids.registration_no_field.value.strip(),
                    national_id=self.ids.national_id_field.value.strip(),
                )
            except Exception as exc:  # noqa: BLE001
                self._set_status(tr("خطا: {}").format(exc))
                return
            self.cancel_edit()
            return

        code = self.ids.code_field.value.strip()
        if not code or not legal_name or not display_name:
            self._set_status("کد، نام حقوقی و نام نمایشی را وارد کنید.")
            return
        try:
            companies_service.create_company(
                code=code,
                legal_name=legal_name,
                display_name=display_name,
                base_currency_id=self._currency_id,
                default_language_id=self._language_id,
                fiscal_year_start_month=fy_month,
                fiscal_year_start_day=fy_day,
                economic_code=self.ids.economic_code_field.value.strip(),
                registration_no=self.ids.registration_no_field.value.strip(),
                national_id=self.ids.national_id_field.value.strip(),
            )
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc))
            return

        self.cancel_edit()
        self._set_status("شرکت با موفقیت اضافه شد.")
