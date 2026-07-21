"""صفحه‌ی مدیریتِ ارزها — فهرستِ سراسریِ ارزها (core.currencies) در پنلِ
راست، و برای ارزِ انتخاب‌شده (اگر ارزِ پایه‌ی شرکتِ جاری نباشد) در پنلِ چپ:
فعال/غیرفعال‌کردنِ آن برایِ شرکتِ جاری + تاریخچه‌ی نرخِ روزانه‌ی تبدیل به
ارزِ پایه — دقیقاً همان الگویِ نوع‌بُعد → حساب‌های تفصیلی در
detail_dimensions.py، اینجا: ارز → نرخ‌های روزانه."""

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
from peecha.services import currencies as currencies_service
from peecha.ui import numerals, theme
from peecha.ui.i18n import tr
from peecha.ui.rtl import shape
from peecha.ui.shortcuts import KeyboardShortcutMixin

_KV_PATH = os.path.join(os.path.dirname(__file__), "currencies.kv")
Builder.load_file(_KV_PATH)


class CurrencyRowWidget(RecycleDataViewBehavior, ButtonBehavior, MDBoxLayout):
    currency_id = NumericProperty(0)
    code_text = StringProperty("")
    symbol_text = StringProperty("")
    decimals_text = StringProperty("")
    status_text = StringProperty("")
    is_active_row = BooleanProperty(True)
    zebra = BooleanProperty(False)
    selected = BooleanProperty(False)
    on_edit = ObjectProperty(None)
    on_delete = ObjectProperty(None)

    def on_release(self) -> None:
        if self.on_edit is not None:
            self.on_edit(self.currency_id)

    def request_delete(self) -> None:
        if self.on_delete is not None:
            self.on_delete(self.currency_id)


Factory.register("CurrencyRowWidget", cls=CurrencyRowWidget)


class ExchangeRateRowWidget(RecycleDataViewBehavior, ButtonBehavior, MDBoxLayout):
    exchange_rate_id = NumericProperty(0)
    date_text = StringProperty("")
    rate_text = StringProperty("")
    zebra = BooleanProperty(False)
    on_delete = ObjectProperty(None)

    def request_delete(self) -> None:
        if self.on_delete is not None:
            self.on_delete(self.exchange_rate_id)


Factory.register("ExchangeRateRowWidget", cls=ExchangeRateRowWidget)


class CurrenciesScreen(KeyboardShortcutMixin, MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._currencies_by_id: dict[int, currencies_service.CurrencyRow] = {}
        self._editing_currency_id: int | None = None
        self._selected_currency_id: int | None = None
        self._rates_by_id: dict[int, currencies_service.ExchangeRateRow] = {}
        self._delete_dialog: MDDialog | None = None

    def on_pre_enter(self, *args):
        self.refresh_currencies()
        self.bind_shortcuts()

    def on_leave(self, *args):
        self.unbind_shortcuts()

    def on_shortcut_save(self) -> None:
        self.save_currency()

    def on_shortcut_cancel(self) -> bool:
        if self._editing_currency_id is not None:
            self.cancel_edit()
            return True
        return False

    def _current_company_id(self) -> int | None:
        return session.current_company.company_id if session.current_company else None

    def _set_status(self, message: str, *, is_error: bool = False) -> None:
        self.ids.status_label.text = shape(message)
        self.ids.status_label.text_color = theme.DANGER if is_error else theme.TEXT_SECONDARY

    def _set_rates_status(self, message: str, *, is_error: bool = False) -> None:
        self.ids.rates_status_label.text = shape(message)
        self.ids.rates_status_label.text_color = theme.DANGER if is_error else theme.TEXT_SECONDARY

    # --- فهرستِ سراسریِ ارزها ---------------------------------------------

    def refresh_currencies(self) -> None:
        rows = currencies_service.list_all_currencies()
        self._currencies_by_id = {r.currency_id: r for r in rows}
        if not rows:
            self.ids.currencies_list.data = [
                {"viewclass": "PEmptyState", "icon": "cash-multiple", "text": shape(tr("هنوز ارزی تعریف نشده است."))}
            ]
        else:
            self.ids.currencies_list.data = [
                {
                    "currency_id": row.currency_id,
                    "on_edit": self.edit_currency,
                    "on_delete": self.confirm_delete_currency,
                    "code_text": row.iso_code,
                    "symbol_text": shape(row.symbol or "—"),
                    "decimals_text": numerals.to_persian_digits(str(row.decimal_places)),
                    "status_text": shape(tr("فعال") if row.is_active else tr("غیرفعال")),
                    "is_active_row": row.is_active,
                    "zebra": i % 2 == 1,
                    "selected": row.currency_id == self._editing_currency_id,
                }
                for i, row in enumerate(rows)
            ]
        if self._selected_currency_id is not None and self._selected_currency_id not in self._currencies_by_id:
            self._select_currency(None)
        elif self._selected_currency_id is not None:
            self._select_currency(self._selected_currency_id)

    def edit_currency(self, currency_id: int) -> None:
        row = self._currencies_by_id.get(currency_id)
        if row is None:
            return
        self._editing_currency_id = currency_id
        self.ids.code_field.set_value(row.iso_code)
        self.ids.symbol_field.set_value(row.symbol or "")
        self.ids.decimals_field.text = numerals.to_persian_digits(str(row.decimal_places))
        self.ids.active_checkbox.active = row.is_active
        self.ids.form_title.text = shape(tr("ویرایشِ ارزِ «{}»").format(row.iso_code))
        self.ids.save_button.text = shape(tr("ذخیره تغییرات"))
        self.ids.cancel_edit_button.opacity = 1
        self.ids.cancel_edit_button.disabled = False
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "36dp"
        self._set_status(tr("در حال ویرایش «{}» — Escape برای لغو.").format(row.iso_code))
        self.refresh_currencies()
        self._select_currency(currency_id)

    def cancel_edit(self) -> None:
        self._editing_currency_id = None
        self.ids.code_field.text = ""
        self.ids.symbol_field.text = ""
        self.ids.decimals_field.text = numerals.to_persian_digits("2")
        self.ids.active_checkbox.active = True
        self.ids.form_title.text = shape(tr("افزودنِ ارزِ تازه"))
        self.ids.save_button.text = shape(tr("افزودن"))
        self.ids.cancel_edit_button.opacity = 0
        self.ids.cancel_edit_button.disabled = True
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "0dp"
        self._set_status(tr(""))
        self.refresh_currencies()

    def save_currency(self) -> None:
        code = self.ids.code_field.value.strip()
        if not code:
            self._set_status(tr("کدِ ارز را وارد کنید."), is_error=True)
            return
        try:
            decimal_places = int(numerals.to_ascii_digits(self.ids.decimals_field.text).strip() or "0")
        except ValueError:
            self._set_status(tr("رقمِ اعشار باید عدد باشد."), is_error=True)
            return
        symbol = self.ids.symbol_field.value.strip()

        if self._editing_currency_id is not None:
            try:
                currencies_service.update_currency(
                    currency_id=self._editing_currency_id,
                    iso_code=code,
                    symbol=symbol,
                    decimal_places=decimal_places,
                    is_active=self.ids.active_checkbox.active,
                )
            except Exception as exc:  # noqa: BLE001 - نمایش هر خطای دیتابیس به کاربر
                self._set_status(tr("خطا: {}").format(exc), is_error=True)
                return
            self.cancel_edit()
            return

        try:
            currency = currencies_service.create_currency(iso_code=code, symbol=symbol, decimal_places=decimal_places)
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc), is_error=True)
            return
        self.ids.code_field.text = ""
        self.ids.symbol_field.text = ""
        self._set_status(tr("ارزِ «{}» افزوده شد.").format(currency.iso_code))
        self.refresh_currencies()

    def confirm_delete_currency(self, currency_id: int) -> None:
        row = self._currencies_by_id.get(currency_id)
        if row is None:
            return
        if self._delete_dialog is not None:
            self._delete_dialog.dismiss()

        def _do_delete(*_args) -> None:
            self._delete_dialog.dismiss()
            self._perform_delete_currency(currency_id)

        self._delete_dialog = MDDialog(
            title=shape(tr("حذفِ ارز")),
            text=shape(tr("ارزِ «{}» حذف شود؟ این کار قابل بازگشت نیست.").format(row.iso_code)),
            buttons=[
                MDFlatButton(text=shape(tr("لغو")), on_release=lambda *_: self._delete_dialog.dismiss()),
                MDRaisedButton(text=shape(tr("حذف")), md_bg_color=theme.DANGER, on_release=_do_delete),
            ],
        )
        self._delete_dialog.open()

    def _perform_delete_currency(self, currency_id: int) -> None:
        try:
            currencies_service.delete_currency(currency_id)
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc), is_error=True)
            return
        if self._editing_currency_id == currency_id:
            self.cancel_edit()
        else:
            self._set_status(tr("ارز حذف شد."))
            self.refresh_currencies()

    # --- تاریخچه‌ی نرخِ ارزِ انتخاب‌شده (برایِ شرکتِ جاری) --------------------

    def _select_currency(self, currency_id: int | None) -> None:
        self._selected_currency_id = currency_id
        self.ids.rate_date_field.text = ""
        self.ids.rate_value_field.text = ""
        self._set_rates_status(tr(""))

        company_id = self._current_company_id()
        if currency_id is None or company_id is None:
            self.ids.rates_panel.opacity = 0
            self.ids.rates_panel.disabled = True
            self.ids.rates_empty_label.opacity = 1
            self.ids.rates_base_hint.opacity = 0
            self.ids.rates_list.data = []
            return

        row = self._currencies_by_id.get(currency_id)
        company = session.current_company
        is_base = company is not None and company.base_currency_id == currency_id

        self.ids.rates_empty_label.opacity = 0
        self.ids.rates_title.text = shape(tr("تاریخچه‌ی نرخِ «{}»").format(row.iso_code))

        if is_base:
            self.ids.rates_panel.opacity = 0
            self.ids.rates_panel.disabled = True
            self.ids.rates_base_hint.opacity = 1
            self.ids.rates_base_hint.text = shape(
                tr("«{}» ارزِ پایه‌ی شرکتِ جاری است؛ نرخِ آن همیشه ۱ است و نیازی به ثبتِ نرخ ندارد.").format(
                    row.iso_code
                )
            )
            self.ids.rates_list.data = []
            return

        self.ids.rates_base_hint.opacity = 0
        self.ids.rates_panel.opacity = 1
        self.ids.rates_panel.disabled = False

        enabled = any(
            c.currency_id == currency_id and c.is_enabled for c in currencies_service.list_company_currencies(company_id)
        )
        self.ids.company_enabled_checkbox.active = enabled
        self.refresh_rates()

    def toggle_company_enabled(self, is_active: bool) -> None:
        company_id = self._current_company_id()
        if company_id is None or self._selected_currency_id is None:
            return
        currencies_service.set_company_currency(company_id, self._selected_currency_id, is_active)

    def refresh_rates(self) -> None:
        company_id = self._current_company_id()
        if company_id is None or self._selected_currency_id is None:
            self.ids.rates_list.data = []
            return
        rows = currencies_service.list_exchange_rates(company_id, self._selected_currency_id)
        self._rates_by_id = {r.exchange_rate_id: r for r in rows}
        if not rows:
            self.ids.rates_list.data = [
                {
                    "viewclass": "PEmptyState",
                    "icon": "calendar-clock-outline",
                    "text": shape(tr("هنوز نرخی برای این ارز ثبت نشده است.")),
                }
            ]
        else:
            self.ids.rates_list.data = [
                {
                    "exchange_rate_id": r.exchange_rate_id,
                    "on_delete": self.confirm_delete_rate,
                    "date_text": numerals.format_jalali_date(r.rate_date),
                    "rate_text": numerals.format_amount(r.rate_to_base),
                    "zebra": i % 2 == 1,
                }
                for i, r in enumerate(rows)
            ]

    def save_rate(self) -> None:
        company_id = self._current_company_id()
        if company_id is None or self._selected_currency_id is None:
            self._set_rates_status(tr("ابتدا یک ارز را انتخاب کنید."), is_error=True)
            return
        try:
            rate_date = numerals.parse_jalali_date(self.ids.rate_date_field.text)
        except ValueError as exc:
            self._set_rates_status(str(exc), is_error=True)
            return
        try:
            rate_to_base = numerals.parse_decimal(self.ids.rate_value_field.text)
        except ValueError as exc:
            self._set_rates_status(str(exc), is_error=True)
            return
        try:
            currencies_service.set_exchange_rate(company_id, self._selected_currency_id, rate_date, rate_to_base)
        except Exception as exc:  # noqa: BLE001
            self._set_rates_status(tr("خطا: {}").format(exc), is_error=True)
            return
        self.ids.rate_date_field.text = ""
        self.ids.rate_value_field.text = ""
        self._set_rates_status(tr("نرخ ذخیره شد."))
        self.refresh_rates()

    def confirm_delete_rate(self, exchange_rate_id: int) -> None:
        company_id = self._current_company_id()
        if company_id is None:
            return
        try:
            currencies_service.delete_exchange_rate(exchange_rate_id, company_id)
        except Exception as exc:  # noqa: BLE001
            self._set_rates_status(tr("خطا: {}").format(exc), is_error=True)
            return
        self._set_rates_status(tr("نرخ حذف شد."))
        self.refresh_rates()
