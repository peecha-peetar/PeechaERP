"""صفحه‌ی صدور سند حسابداری: هدر سند + ردیف‌های بدهکار/بستانکار پویا +
فهرست اسناد اخیر (با ویرایش/حذف).

هر ردیف یک JournalEntryLineRow است (تعریف در همین فایل، نه widgets.py،
چون فقط همین صفحه از آن استفاده می‌کند). موازنه‌ی بدهکار/بستانکار به‌صورت
زنده با هر تغییرِ مبلغ محاسبه می‌شود؛ اعتبارسنجیِ نهایی (شامل قابل‌ثبت‌بودنِ
حساب و برابریِ دقیق مبالغ) در services/journal_entries.py انجام می‌شود.

فقط سندهای با وضعیت TEMPORARY قابل ویرایش/حذف‌اند (چون هنوز جریان تاییدِ
کارتابل ساخته نشده، همه‌ی سندها فعلاً TEMPORARY هستند، طبق طراحی دیتابیس:
«موقت: قابل ویرایش/ادغام»)."""

from __future__ import annotations

import datetime
import decimal
import os

from kivy.factory import Factory
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, ObjectProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.dropdown import DropDown
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen

from peecha import session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import currencies as currencies_service
from peecha.services import detail_dimensions as dimensions_service
from peecha.services import field_labels as field_labels_service
from peecha.services import journal_entries as je_service
from peecha.ui import numerals, theme
from peecha.ui.i18n import tr
from peecha.ui.rtl import shape
from peecha.ui.shortcuts import KeyboardShortcutMixin
from peecha.ui.widgets import PSelectField, PTextField, open_rtl_dropdown

_KV_PATH = os.path.join(os.path.dirname(__file__), "journal_entry.kv")
Builder.load_file(_KV_PATH)

_STATUS_LABELS = {"TEMPORARY": "موقت", "PERMANENT": "دائم", "REVERSED": "برگشت‌خورده", "CANCELLED": "ابطال‌شده"}
_STATUS_COLORS = {
    "TEMPORARY": theme.WARNING,
    "PERMANENT": theme.SUCCESS,
    "REVERSED": theme.DANGER,
    "CANCELLED": theme.TEXT_DISABLED,
}


class _AccountOptionRow(ButtonBehavior, MDBoxLayout):
    """یک ردیف از نتایجِ جستجوی زنده‌ی AccountSearchField."""

    label_text = StringProperty("")
    highlighted = BooleanProperty(False)

    def __init__(self, account_row: coa_service.AccountRow, on_choose, **kwargs):
        super().__init__(**kwargs)
        self.account_row = account_row
        self._on_choose = on_choose

    def on_release(self) -> None:
        self._on_choose(self.account_row)


class AccountSearchField(PTextField):
    """فیلدِ کدِ حساب با جستجوی همزمان: طبق درخواستِ صریح، با هر کاراکترِ
    تایپ‌شده نتایج بلافاصله فیلتر می‌شوند (روی full_code و نام)، بالا/پایین
    بینِ نتایجِ نمایش‌داده‌شده حرکت می‌کند و Enter نتیجه‌ی هایلایت‌شده را
    انتخاب می‌کند. چون هر نمونه به داده‌ی مخصوصِ خودش (فهرستِ حساب‌ها،
    کال‌بکِ انتخاب) نیاز دارد که در KV قابل‌تعریف نیست، در پایتون
    (JournalEntryLineRow) ساخته و در یک جایگاهِ KV جاگذاری می‌شود، نه
    مستقیم در KV اعلام می‌شود."""

    def __init__(self, account_options: list[coa_service.AccountRow], on_select, **kwargs):
        kwargs.setdefault("persian_digits", True)
        kwargs.setdefault("hint_text", shape(tr("جستجوی کد یا نام حساب")))
        # خودش با انتخاب یک نتیجه مستقیم self.text = shape(...) می‌کند؛ اگر
        # PTextField هم روی این (متنِ از قبل shape‌شده) دوباره shape() صدا
        # بزند، خرابش می‌کند — پس مکانیزمِ خودکارِ کلاسِ پایه اینجا خاموش است.
        kwargs.setdefault("auto_shape_display", False)
        super().__init__(**kwargs)
        self.account_options = account_options
        self._on_select = on_select
        self.account_id: int | None = None
        self._results: list[coa_service.AccountRow] = []
        self._highlighted_index = -1
        self._suppress_filter = False
        self._dropdown = DropDown(auto_width=False, max_height=dp(240))
        self._dropdown.width = dp(340)
        self.bind(text=self._on_text_changed)
        self.bind(focus=self._on_focus_changed)

    def _on_focus_changed(self, _instance, focused: bool) -> None:
        # عمداً با گرفتنِ فوکوس منو باز نمی‌شود (فقط با تایپِ کاراکتر، طبق
        # درخواستِ صریح) — چون فوکوسِ خودکارِ فرم روی ردیفِ تازه‌ساخته (در
        # _reset_form/_focus_after_row) در همان فریمی می‌افتد که Kivy هنوز
        # موقعیتِ نهاییِ ویجت را layout نکرده؛ بازکردنِ منو در آن لحظه با
        # مختصاتِ نادرست محاسبه می‌شود (با تست مستقیم پیدا شد: منو روی نوار
        # کناری می‌افتد). با اولین کاراکترِ واقعی که کاربر تایپ می‌کند، لایه‌بندی
        # قطعاً تمام شده و این مشکل وجود ندارد.
        if not focused:
            self._dropdown.dismiss()

    def _on_text_changed(self, _instance, value: str) -> None:
        if self._suppress_filter:
            return
        self.account_id = None
        self._filter_and_show(value)

    def _filter_and_show(self, query: str) -> None:
        query_norm = numerals.to_ascii_digits(query).strip()
        if not query_norm:
            self._results = list(self.account_options)
        else:
            self._results = [
                row for row in self.account_options if query_norm in row.full_code or query_norm in row.name
            ]
        self._highlighted_index = 0 if self._results else -1
        self._rebuild_dropdown()
        if self._results and self.focus:
            # چون persian_digits=True با هر تایپِ رقم یک‌بار دیگر خودش را
            # صدا می‌زند (تبدیل رقم → بازتنظیمِ text → دوباره این متد، طبق
            # همان الگوی موجود در PTextField._persianize_on_text)، اگر منو
            # از قبل باز باشد نباید دوباره open() صدا زده شود — DropDown
            # با فراخوانیِ تودرتوی open() روی همان ویجت کرش می‌کند (تست
            # مستقیم تایید کرد: «قبلاً یک والد دارد»).
            if self._dropdown.attach_to is None:
                self._dropdown.open(self)
        else:
            self._dropdown.dismiss()

    def _rebuild_dropdown(self) -> None:
        self._dropdown.clear_widgets()
        for i, row in enumerate(self._results):
            self._dropdown.add_widget(
                _AccountOptionRow(
                    account_row=row,
                    on_choose=self._select,
                    label_text=shape(f"{numerals.to_persian_digits(row.full_code)} — {row.name}"),
                    highlighted=(i == self._highlighted_index),
                )
            )

    def _move_highlight(self, delta: int) -> None:
        if not self._results:
            return
        self._highlighted_index = (self._highlighted_index + delta) % len(self._results)
        self._rebuild_dropdown()

    def _select(self, account_row: coa_service.AccountRow) -> None:
        self.set_selected(account_row)
        self._dropdown.dismiss()
        self._on_select()

    def set_selected(self, account_row: coa_service.AccountRow) -> None:
        """پیش‌پرکردنِ فیلد (مثلاً هنگام بارگذاریِ سند برای ویرایش) بدونِ
        بازکردنِ منو یا صدازدنِ on_select."""
        self.account_id = account_row.account_id
        self._suppress_filter = True
        self.text = shape(f"{numerals.to_persian_digits(account_row.full_code)} — {account_row.name}")
        self._suppress_filter = False

    def keyboard_on_key_down(self, window, keycode, text, modifiers):
        key = keycode[0]
        if key == 273:  # بالا
            self._move_highlight(-1)
            return True
        if key == 274:  # پایین
            self._move_highlight(1)
            return True
        if key in (13, 271):  # اینتر / اینترِ صفحه‌کلیدِ عددی
            if self._results and 0 <= self._highlighted_index < len(self._results):
                self._select(self._results[self._highlighted_index])
            return True
        if key == 27 and self._dropdown.attach_to is not None:  # Escape فقط منو را می‌بندد، نه کل فرم را
            self._dropdown.dismiss()
            return True
        return super().keyboard_on_key_down(window, keycode, text, modifiers)


class _SuggestionRow(ButtonBehavior, MDBoxLayout):
    """یک ردیفِ نتیجه‌ی پیشنهادِ شرح — مشابهِ _AccountOptionRow."""

    label_text = StringProperty("")
    highlighted = BooleanProperty(False)

    def __init__(self, suggestion_text: str, on_choose, **kwargs):
        super().__init__(**kwargs)
        self.suggestion_text = suggestion_text
        self._on_choose = on_choose

    def on_release(self) -> None:
        self._on_choose(self.suggestion_text)


class LineDescriptionField(PTextField):
    """فیلدِ شرحِ ردیف با پیشنهادِ زنده از شرح‌های قبلاً واردشده‌ی همین
    شرکت (طبق درخواستِ صریح: «در هنگام تایپ خودش هم کلمه پیشنهاد بده»).
    انتخابِ یک پیشنهاد (کلیک یا Enترِ روی گزینه‌ی هایلایت‌شده) هم مقدار را
    می‌گذارد هم — دقیقاً مثلِ AccountSearchField — بلافاصله به فیلدِ بعدی
    (بدهکار) می‌رود؛ اگر منویی باز نباشد، Enterِ معمولی هم به همان فیلدِ
    بعدی می‌رود (با focus_next که JournalEntryLineRow وصل می‌کند)."""

    def __init__(self, suggestions_provider, **kwargs):
        kwargs.setdefault("hint_text", shape(tr("شرح ردیف")))
        super().__init__(**kwargs)
        self._suggestions_provider = suggestions_provider
        self._results: list[str] = []
        self._highlighted_index = -1
        self._dropdown = DropDown(auto_width=False, max_height=dp(180))
        self._dropdown.width = dp(280)
        self.bind(text=self._on_text_changed)
        self.bind(focus=self._on_focus_changed)
        self.bind(on_text_validate=self._on_default_validate)

    def _on_focus_changed(self, _instance, focused: bool) -> None:
        if not focused:
            self._dropdown.dismiss()

    def _on_text_changed(self, _instance, value: str) -> None:
        query = value.strip()
        if not query:
            self._results = []
            self._dropdown.dismiss()
            return
        suggestions = self._suggestions_provider()
        self._results = [s for s in suggestions if query in s and s != query][:8]
        self._highlighted_index = 0 if self._results else -1
        self._rebuild_dropdown()
        if self._results and self.focus:
            if self._dropdown.attach_to is None:
                self._dropdown.open(self)
        else:
            self._dropdown.dismiss()

    def _rebuild_dropdown(self) -> None:
        self._dropdown.clear_widgets()
        for i, text in enumerate(self._results):
            self._dropdown.add_widget(
                _SuggestionRow(
                    suggestion_text=text,
                    on_choose=self._select,
                    label_text=shape(text),
                    highlighted=(i == self._highlighted_index),
                )
            )

    def _move_highlight(self, delta: int) -> None:
        if not self._results:
            return
        self._highlighted_index = (self._highlighted_index + delta) % len(self._results)
        self._rebuild_dropdown()

    def _select(self, text: str) -> None:
        self.set_value(text)
        self._dropdown.dismiss()
        self._results = []
        if self.focus_next:
            self.focus_next.focus = True

    def _on_default_validate(self, *_args) -> None:
        if self.focus_next:
            self.focus_next.focus = True

    def keyboard_on_key_down(self, window, keycode, text, modifiers):
        key = keycode[0]
        if key == 273 and self._dropdown.attach_to is not None:  # بالا
            self._move_highlight(-1)
            return True
        if key == 274 and self._dropdown.attach_to is not None:  # پایین
            self._move_highlight(1)
            return True
        if key in (13, 271) and self._dropdown.attach_to is not None and self._results:
            self._select(self._results[self._highlighted_index])
            return True
        if key == 27 and self._dropdown.attach_to is not None:  # Escape فقط منو را می‌بندد
            self._dropdown.dismiss()
            return True
        return super().keyboard_on_key_down(window, keycode, text, modifiers)


class _LineDimensionsContent(MDBoxLayout):
    """محتوایِ دیالوگِ انتخابِ ابعادِ تفصیلیِ یک ردیف — برای هر نوع‌بُعدِ
    الزامیِ حسابِ انتخاب‌شده، یک PSelectField می‌سازد که با کلیک، منویِ
    حساب‌های تفصیلیِ فعالِ همان نوع را (open_rtl_dropdown) باز می‌کند."""

    def __init__(self, required_dimensions: list[dimensions_service.RequiredDimension], initial_values: dict[int, int], **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("spacing", dp(12))
        super().__init__(**kwargs)
        self.bind(minimum_height=self.setter("height"))
        self.values: dict[int, int] = dict(initial_values)
        self._menus: dict[int, MDDropdownMenu] = {}
        for dim in required_dimensions:
            row = MDBoxLayout(orientation="vertical", size_hint_y=None, height=dp(66), spacing=dp(4))
            row.add_widget(
                Factory.PLabel(
                    text=shape(dim.code), font_style="Caption", size_hint_y=None, height=dp(20), valign="middle"
                )
            )
            select = PSelectField(text=self._label_for(dim, initial_values.get(dim.dimension_type_id)))
            select.bind(on_release=lambda _inst, d=dim, s=select: self._open_menu(d, s))
            row.add_widget(select)
            self.add_widget(row)

    def _label_for(self, dim: dimensions_service.RequiredDimension, detail_account_id: int | None) -> str:
        if detail_account_id is not None:
            match = next((d for d in dim.detail_accounts if d.detail_account_id == detail_account_id), None)
            if match is not None:
                return shape(match.code)
        return shape(tr("— انتخاب کنید —"))

    def _open_menu(self, dim: dimensions_service.RequiredDimension, select_widget: PSelectField) -> None:
        items = [
            {
                "text": shape(d.code),
                "on_release": lambda detail_id=d.detail_account_id, code=d.code: self._choose(
                    dim.dimension_type_id, detail_id, code, select_widget
                ),
            }
            for d in dim.detail_accounts
        ]
        self._menus[dim.dimension_type_id] = open_rtl_dropdown(select_widget, items, width_mult=3)

    def _choose(self, dimension_type_id: int, detail_account_id: int, code: str, select_widget: PSelectField) -> None:
        menu = self._menus.get(dimension_type_id)
        if menu is not None:
            menu.dismiss()
        self.values[dimension_type_id] = detail_account_id
        select_widget.text = shape(code)


class _LineCurrencyContent(MDBoxLayout):
    """محتوایِ دیالوگِ انتخابِ ارزِ یک ردیف — با انتخابِ ارزِ غیرِپایه، فیلدِ
    نرخِ تبدیل ظاهر می‌شود و در صورتِ نبودنِ مقدار، از آخرین نرخِ ثبت‌شده
    برای همان ارز/تاریخ (currencies_service.get_latest_rate) پیش‌پر می‌شود."""

    def __init__(
        self,
        transactable_currencies: list[currencies_service.CurrencyRow],
        base_currency_id: int,
        company_id: int,
        document_date: datetime.date,
        initial_currency_id: int | None,
        initial_rate: decimal.Decimal | None,
        **kwargs,
    ):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("spacing", dp(12))
        super().__init__(**kwargs)
        self.bind(minimum_height=self.setter("height"))
        self._currencies = transactable_currencies
        self._currencies_by_id = {c.currency_id: c for c in transactable_currencies}
        self.base_currency_id = base_currency_id
        self.company_id = company_id
        self.document_date = document_date
        self.currency_id = initial_currency_id or base_currency_id
        self._menu: MDDropdownMenu | None = None

        currency_row = MDBoxLayout(orientation="vertical", size_hint_y=None, height=dp(66), spacing=dp(4))
        currency_row.add_widget(
            Factory.PLabel(text=shape(tr("ارزِ ردیف")), font_style="Caption", size_hint_y=None, height=dp(20))
        )
        self.currency_select = PSelectField(text=self._label_for_currency(self.currency_id))
        self.currency_select.bind(on_release=self._open_currency_menu)
        currency_row.add_widget(self.currency_select)
        self.add_widget(currency_row)

        self.rate_row = MDBoxLayout(orientation="vertical", size_hint_y=None, height=dp(66), spacing=dp(4))
        self.rate_row.add_widget(
            Factory.PLabel(
                text=shape(tr("نرخِ تبدیل به ارزِ پایه")), font_style="Caption", size_hint_y=None, height=dp(20)
            )
        )
        self.rate_field = PTextField(persian_digits=True)
        if initial_rate is not None:
            self.rate_field.text = numerals.to_persian_digits(str(initial_rate))
        self.rate_row.add_widget(self.rate_field)
        self.add_widget(self.rate_row)
        self._refresh_rate_visibility()

    def _label_for_currency(self, currency_id: int) -> str:
        currency = self._currencies_by_id.get(currency_id)
        return shape(currency.iso_code if currency else "")

    def _open_currency_menu(self, *_args) -> None:
        items = [
            {"text": shape(c.iso_code), "on_release": lambda cid=c.currency_id: self._choose_currency(cid)}
            for c in self._currencies
        ]
        self._menu = open_rtl_dropdown(self.currency_select, items, width_mult=3)

    def _choose_currency(self, currency_id: int) -> None:
        if self._menu is not None:
            self._menu.dismiss()
        self.currency_id = currency_id
        self.currency_select.text = self._label_for_currency(currency_id)
        self._refresh_rate_visibility()
        if currency_id != self.base_currency_id and not self.rate_field.text.strip():
            latest = currencies_service.get_latest_rate(self.company_id, currency_id, self.document_date)
            if latest is not None:
                self.rate_field.text = numerals.to_persian_digits(str(latest))

    def _refresh_rate_visibility(self) -> None:
        is_base = self.currency_id == self.base_currency_id
        self.rate_row.opacity = 0 if is_base else 1
        self.rate_row.disabled = is_base
        self.rate_row.height = 0 if is_base else dp(66)


class JournalEntryLineRow(MDBoxLayout):
    has_required_dims = BooleanProperty(False)
    dims_complete = BooleanProperty(True)
    has_multi_currency = BooleanProperty(False)
    currency_is_base = BooleanProperty(True)

    def __init__(
        self,
        account_options,
        on_change,
        on_remove,
        on_validate,
        description_suggestions,
        on_amount_text,
        transactable_currencies,
        base_currency_id,
        company_id,
        get_document_date,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._on_change = on_change
        self._on_remove = on_remove
        self._on_validate = on_validate
        self._on_amount_text = on_amount_text
        self.account_field = AccountSearchField(account_options=account_options, on_select=self._account_selected)
        self.ids.account_slot.add_widget(self.account_field)

        self.description_field = LineDescriptionField(suggestions_provider=description_suggestions)
        self.ids.description_slot.add_widget(self.description_field)

        self.account_field.focus_next = self.description_field
        self.description_field.focus_previous = self.account_field
        self.description_field.focus_next = self.ids.debit_field
        self.ids.debit_field.focus_previous = self.description_field

        self.dimension_values: dict[int, int] = {}
        self._required_dimensions: list[dimensions_service.RequiredDimension] = []
        self._dimensions_dialog: MDDialog | None = None

        self.transactable_currencies = transactable_currencies
        self.base_currency_id = base_currency_id
        self.company_id = company_id
        self._get_document_date = get_document_date
        self.line_currency_id: int | None = None
        self.line_exchange_rate: decimal.Decimal | None = None
        self.has_multi_currency = len(transactable_currencies) > 1
        self._currency_dialog: MDDialog | None = None

    @property
    def account_id(self) -> int | None:
        return self.account_field.account_id

    def set_account(self, account_row: coa_service.AccountRow) -> None:
        self.account_field.set_selected(account_row)

    def _account_selected(self) -> None:
        # طبق درخواستِ صریح: بعدِ انتخابِ حساب، فوکوس به فیلدِ شرحِ همین
        # ردیف می‌رود (نه مستقیم به بدهکار).
        self.dimension_values = {}
        self.load_required_dimensions()
        self._on_change()
        self.description_field.focus = True

    def load_required_dimensions(self) -> None:
        # با انتخابِ یک حسابِ تازه (یا بارگذاریِ سند برای ویرایش)، نوع‌بُعدهای
        # الزامیِ همان حساب دوباره از سرویس خوانده می‌شود — چون هر حساب
        # ممکن است نوع‌بُعدهای متفاوتی الزامی کرده باشد.
        self._required_dimensions = (
            dimensions_service.get_required_dimensions_for_account(self.account_id) if self.account_id else []
        )
        self.has_required_dims = bool(self._required_dimensions)
        self._update_dims_complete()

    def _update_dims_complete(self) -> None:
        self.dims_complete = all(
            dim.dimension_type_id in self.dimension_values for dim in self._required_dimensions
        )

    def open_dimensions_dialog(self) -> None:
        if not self._required_dimensions:
            return
        if self._dimensions_dialog is not None:
            self._dimensions_dialog.dismiss()

        content = _LineDimensionsContent(self._required_dimensions, self.dimension_values)

        def _apply(*_args) -> None:
            self.dimension_values = dict(content.values)
            self._dimensions_dialog.dismiss()
            self._update_dims_complete()

        self._dimensions_dialog = MDDialog(
            title=shape(tr("ابعادِ تفصیلیِ ردیف")),
            type="custom",
            content_cls=content,
            buttons=[
                MDFlatButton(text=shape(tr("لغو")), on_release=lambda *_: self._dimensions_dialog.dismiss()),
                MDRaisedButton(text=shape(tr("تایید")), on_release=_apply),
            ],
        )
        self._dimensions_dialog.open()

    def open_currency_dialog(self) -> None:
        if not self.has_multi_currency:
            return
        if self._currency_dialog is not None:
            self._currency_dialog.dismiss()

        content = _LineCurrencyContent(
            transactable_currencies=self.transactable_currencies,
            base_currency_id=self.base_currency_id,
            company_id=self.company_id,
            document_date=self._get_document_date(),
            initial_currency_id=self.line_currency_id,
            initial_rate=self.line_exchange_rate,
        )

        def _apply(*_args) -> None:
            if content.currency_id == self.base_currency_id:
                self.line_currency_id = None
                self.line_exchange_rate = None
            else:
                self.line_currency_id = content.currency_id
                try:
                    self.line_exchange_rate = numerals.parse_decimal(content.rate_field.text)
                except ValueError:
                    self.line_exchange_rate = None
            self._currency_dialog.dismiss()
            self._update_currency_state()

        self._currency_dialog = MDDialog(
            title=shape(tr("ارزِ ردیف")),
            type="custom",
            content_cls=content,
            buttons=[
                MDFlatButton(text=shape(tr("لغو")), on_release=lambda *_: self._currency_dialog.dismiss()),
                MDRaisedButton(text=shape(tr("تایید")), on_release=_apply),
            ],
        )
        self._currency_dialog.open()

    def _update_currency_state(self) -> None:
        self.currency_is_base = self.line_currency_id is None

    def on_debit_changed(self) -> None:
        if self.ids.debit_field.text.strip():
            self.ids.credit_field.text = ""
        self._on_change()
        self._on_amount_text(self.ids.debit_field.text)

    def on_credit_changed(self) -> None:
        if self.ids.credit_field.text.strip():
            self.ids.debit_field.text = ""
        self._on_change()
        self._on_amount_text(self.ids.credit_field.text)

    def on_amount_focus(self, field) -> None:
        # طبق درخواستِ صریح، «لایو» یعنی همان لحظه‌ی رفتن روی فیلد هم مبلغِ
        # موجود (نه فقط تایپِ تازه) به حروف نمایش داده شود.
        if field.focus:
            self._on_amount_text(field.text)

    def on_debit_validate(self) -> None:
        # طبق درخواستِ صریح: اگر بدهکار مقداری غیرصفر دارد، Enter به ردیفِ
        # بعد می‌رود؛ اگر خالی/صفر است (این ردیف قرار است بستانکار باشد)
        # Enter فقط به فیلدِ بستانکارِ همین ردیف می‌رود.
        raw = numerals.to_ascii_digits(self.ids.debit_field.text).strip()
        if raw and raw != "0":
            self.request_next()
        else:
            self.ids.credit_field.focus = True

    def request_next(self) -> None:
        self._on_validate(self)

    def remove_line(self) -> None:
        self._on_remove(self)


class JournalEntryRowWidget(RecycleDataViewBehavior, ButtonBehavior, MDBoxLayout):
    """یک ردیفِ جدولِ «اسناد اخیر»: کلیک روی ردیف = بارگذاری برای ویرایش.

    طبق تست مستقیم روی chart_of_accounts (همان الگو): فهرستِ BoxLayout+
    add_widget-در-حلقه با تعدادِ زیادِ اسناد به‌شدت کند می‌شود (O(n²) چون
    هر add_widget کلِ چیدمانِ فرزندهای قبلی را دوباره محاسبه می‌کند).
    اسنادِ حسابداری دقیقاً همان چیزی هستند که با استفاده‌ی واقعی به‌سرعت
    زیاد می‌شوند، پس RecycleView اینجا اهمیتِ ویژه‌ای دارد."""

    journal_entry_id = NumericProperty(0)
    number_text = StringProperty("")
    date_text = StringProperty("")
    description_text = StringProperty("")
    amount_text = StringProperty("")
    status_text = StringProperty("")
    status_badge_color = ListProperty([0, 0, 0, 1])
    zebra = BooleanProperty(False)
    editable = BooleanProperty(False)
    selected = BooleanProperty(False)
    on_edit = ObjectProperty(None)
    on_delete = ObjectProperty(None)

    def on_release(self) -> None:
        if self.editable and self.on_edit is not None:
            self.on_edit(self.journal_entry_id)

    def request_delete(self) -> None:
        if self.editable and self.on_delete is not None:
            self.on_delete(self.journal_entry_id)


Factory.register("JournalEntryRowWidget", cls=JournalEntryRowWidget)


class JournalEntryScreen(KeyboardShortcutMixin, MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._account_options: list[coa_service.AccountRow] = []
        self._description_suggestions: list[str] = []
        self._transactable_currencies: list[currencies_service.CurrencyRow] = []
        self._base_currency_id: int | None = None
        self._rows: list[JournalEntryLineRow] = []
        self._editing_entry_id: int | None = None
        self._delete_dialog: MDDialog | None = None
        self._field_labels: dict[str, str] = {}
        self._form_initialized = False

    def on_pre_enter(self, *args):
        self._load_accounts()
        self.apply_field_labels()
        # طبق درخواستِ صریح: با رفتن به فرمِ دیگر و برگشتن به این صفحه،
        # اطلاعاتِ نیمه‌واردشده نباید پاک شود — پس _reset_form() فقط بارِ
        # اولی که این صفحه باز می‌شود صدا زده می‌شود، نه هر بار. (بازنشانیِ
        # آگاهانه/عمدی همچنان از طریق cancel_edit()/Escape یا بعدِ ثبتِ
        # موفق ممکن است.)
        if not self._form_initialized:
            self._reset_form()
            self._form_initialized = True
        self._set_status(tr(""))
        self.refresh_entries()
        self.bind_shortcuts()

    def apply_field_labels(self) -> None:
        language_id = session.current_language.language_id if session.current_language else None
        self._field_labels = {k: tr(v) for k, v in field_labels_service.get_labels_map("journal_entry", language_id).items()}
        self.ids.description_field.hint_text = shape(self._field_labels["description"])
        self.ids.date_field.hint_text = shape(self._field_labels["date"])
        for row in self._rows:
            self._apply_line_labels(row)

    def _apply_line_labels(self, row: JournalEntryLineRow) -> None:
        if not self._field_labels:
            return
        row.account_field.hint_text = shape(self._field_labels["line_account"])
        row.description_field.hint_text = shape(self._field_labels["line_description"])
        row.ids.debit_field.hint_text = shape(self._field_labels["line_debit"])
        row.ids.credit_field.hint_text = shape(self._field_labels["line_credit"])

    def on_leave(self, *args):
        self.unbind_shortcuts()

    def on_shortcut_save(self) -> None:
        self.save_entry()

    def on_shortcut_cancel(self) -> bool:
        if self._editing_entry_id is not None:
            self.cancel_edit()
            return True
        return False

    def on_shortcut_delete(self) -> bool:
        if self._editing_entry_id is not None:
            self.confirm_delete(self._editing_entry_id)
            return True
        return False

    def _load_accounts(self) -> None:
        if session.current_company is None:
            self._account_options = []
            self._description_suggestions = []
            self._transactable_currencies = []
            self._base_currency_id = None
        else:
            self._account_options = coa_service.list_postable_accounts(session.current_company.company_id)
            self._description_suggestions = je_service.list_recent_line_descriptions(session.current_company.company_id)
            self._transactable_currencies = currencies_service.list_transactable_currencies(
                session.current_company.company_id
            )
            self._base_currency_id = session.current_company.base_currency_id

    def _get_document_date(self) -> datetime.date:
        try:
            return numerals.parse_jalali_date(self.ids.date_field.text)
        except ValueError:
            return datetime.date.today()

    def _reset_form(self) -> None:
        # توجه: پیام وضعیت (مثلاً «سند ثبت شد») را عمداً اینجا پاک نمی‌کنیم؛
        # save_entry() بعد از ثبت موفق همین متد را صدا می‌زند تا فرم برای سند
        # بعدی خالی شود، اما پیام موفقیت باید روی صفحه باقی بماند.
        self._editing_entry_id = None
        self.ids.lines_box.clear_widgets()
        self._rows = []
        self.ids.date_field.text = numerals.format_jalali_date(datetime.date.today())
        self.ids.description_field.text = ""
        self.ids.amount_words_label.text = ""
        self.ids.form_title.text = shape(tr("صدور سند حسابداری"))
        self.ids.save_button.text = shape(tr("ثبت سند"))
        self.ids.cancel_edit_button.opacity = 0
        self.ids.cancel_edit_button.disabled = True
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "0dp"
        self.add_line()
        self.add_line()
        self._recalculate()
        # طبق درخواستِ صریح: نقطه‌ی شروعِ کیبوردِ سند تاریخ است — با Enter
        # به شرحِ سند، بعد به کدِ حسابِ ردیفِ اول می‌رود (زنجیره‌ی focus_next).
        self.ids.date_field.focus = True

    def update_amount_words(self, raw_text: str) -> None:
        # طبق درخواستِ صریح: مبلغِ واردشده به‌صورتِ زنده زیرِ فرم به حروف
        # نمایش داده می‌شود؛ اگر مقدار خالی/صفر/نامعتبر باشد برچسب خالی می‌شود.
        try:
            value = numerals.parse_decimal(raw_text)
        except ValueError:
            self.ids.amount_words_label.text = ""
            return
        if not value:
            self.ids.amount_words_label.text = ""
            return
        self.ids.amount_words_label.text = shape(numerals.amount_to_words(value))

    def add_line(self) -> None:
        row = JournalEntryLineRow(
            account_options=self._account_options,
            on_change=self._recalculate,
            on_remove=self._remove_line,
            on_validate=self._focus_after_row,
            description_suggestions=lambda: self._description_suggestions,
            on_amount_text=self.update_amount_words,
            transactable_currencies=self._transactable_currencies,
            base_currency_id=self._base_currency_id,
            company_id=session.current_company.company_id if session.current_company else None,
            get_document_date=self._get_document_date,
        )
        self._rows.append(row)
        self.ids.lines_box.add_widget(row)
        self._apply_line_labels(row)
        self._relink_row_focus()

    def _remove_line(self, row: JournalEntryLineRow) -> None:
        if row in self._rows:
            self._rows.remove(row)
            self.ids.lines_box.remove_widget(row)
            self._relink_row_focus()
            self._recalculate()

    def _relink_row_focus(self) -> None:
        """زنجیره‌ی Tab بین ردیف‌های پویا را دوباره می‌سازد — چون هر بار
        ردیفی اضافه/حذف می‌شود، فیلد آخرِ سطرِ قبل باید به اولین فیلدِ سطرِ
        بعد وصل شود، و این با focus_next ایستا در KV ممکن نیست."""
        if not self._rows:
            self.ids.description_field.focus_next = self.ids.add_line_button
            return
        self.ids.description_field.focus_next = self._rows[0].account_field
        for i, row in enumerate(self._rows):
            if i + 1 < len(self._rows):
                row.ids.credit_field.focus_next = self._rows[i + 1].account_field
                self._rows[i + 1].account_field.focus_previous = row.ids.credit_field
            else:
                row.ids.credit_field.focus_next = self.ids.add_line_button

    def _focus_after_row(self, row: JournalEntryLineRow) -> None:
        """Enter در فیلد بدهکار/بستانکارِ آخرین ردیف: ردیف جدید اضافه و
        فوکوس به آن منتقل می‌شود (مثل صفحه‌گسترده) — Enter در بقیه‌ی
        ردیف‌ها فقط به ردیف بعدی می‌رود."""
        if row is self._rows[-1]:
            self.add_line()
            self._rows[-1].account_field.focus = True
        else:
            idx = self._rows.index(row)
            self._rows[idx + 1].account_field.focus = True

    def _recalculate(self) -> None:
        total_debit = decimal.Decimal(0)
        total_credit = decimal.Decimal(0)
        for row in self._rows:
            try:
                total_debit += numerals.parse_decimal(row.ids.debit_field.text)
                total_credit += numerals.parse_decimal(row.ids.credit_field.text)
            except ValueError:
                pass  # حین تایپ مقدار ناقص عادی است؛ فقط در ثبت نهایی خطا نشان داده می‌شود

        self.ids.total_debit_label.text = shape(tr("جمع بدهکار: {}").format(numerals.format_amount(total_debit)))
        self.ids.total_credit_label.text = shape(tr("جمع بستانکار: {}").format(numerals.format_amount(total_credit)))

        balanced = total_debit == total_credit and total_debit > 0
        chip_color = theme.SUCCESS if balanced else theme.DANGER
        self.ids.balance_label.text = shape(tr("متعادل") if balanced else tr("نامتعادل"))
        self.ids.balance_label.text_color = chip_color
        self.ids.balance_chip.md_bg_color = (chip_color[0], chip_color[1], chip_color[2], 0.12)

    def _set_status(self, message: str, *, is_error: bool = False) -> None:
        self.ids.status_label.text = shape(message)
        self.ids.status_label.text_color = theme.DANGER if is_error else theme.TEXT_SECONDARY

    def _collect_lines(self) -> list[je_service.LineInput] | None:
        lines: list[je_service.LineInput] = []
        for row in self._rows:
            if row.account_id is None:
                continue
            try:
                debit = numerals.parse_decimal(row.ids.debit_field.text)
                credit = numerals.parse_decimal(row.ids.credit_field.text)
            except ValueError as exc:
                self._set_status(str(exc), is_error=True)
                return None
            lines.append(
                je_service.LineInput(
                    account_id=row.account_id,
                    description=row.description_field.value.strip(),
                    debit=debit,
                    credit=credit,
                    details=dict(row.dimension_values),
                    currency_id=row.line_currency_id,
                    exchange_rate=row.line_exchange_rate,
                )
            )
        return lines

    def save_entry(self) -> None:
        if session.current_company is None or session.current_user is None:
            self._set_status(tr("کاربر یا شرکت جاری نامعتبر است."), is_error=True)
            return

        try:
            document_date = numerals.parse_jalali_date(self.ids.date_field.text)
        except ValueError as exc:
            self._set_status(str(exc), is_error=True)
            return

        lines = self._collect_lines()
        if lines is None:
            return

        try:
            if self._editing_entry_id is not None:
                je_service.update_journal_entry(
                    journal_entry_id=self._editing_entry_id,
                    company_id=session.current_company.company_id,
                    document_date=document_date,
                    description=self.ids.description_field.value.strip(),
                    lines=lines,
                    changed_by_user_id=session.current_user.user_id,
                )
                message = "سند به‌روزرسانی شد."
            else:
                result = je_service.create_journal_entry(
                    company_id=session.current_company.company_id,
                    created_by_user_id=session.current_user.user_id,
                    document_date=document_date,
                    description=self.ids.description_field.value.strip(),
                    lines=lines,
                )
                message = f"سند با شماره‌ی موقت {numerals.to_persian_digits(str(result.temporary_no))} ثبت شد."
        except Exception as exc:  # noqa: BLE001 - نمایش هر خطای اعتبارسنجی/دیتابیس به کاربر
            self._set_status(tr("خطا: {}").format(exc), is_error=True)
            return

        self._reset_form()
        self._set_status(message)
        self.refresh_entries()

    def edit_entry(self, journal_entry_id: int) -> None:
        if session.current_company is None:
            return
        try:
            lines = je_service.get_journal_entry_lines(journal_entry_id)
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc), is_error=True)
            return

        entries = je_service.list_journal_entries(session.current_company.company_id)
        entry = next((e for e in entries if e.journal_entry_id == journal_entry_id), None)
        if entry is None:
            return

        self._editing_entry_id = journal_entry_id
        self.ids.lines_box.clear_widgets()
        self._rows = []
        self.ids.date_field.text = numerals.format_jalali_date(entry.document_date)
        self.ids.description_field.set_value(entry.description)
        accounts_by_id = {a.account_id: a for a in self._account_options}
        for ln in lines:
            self.add_line()
            row = self._rows[-1]
            account = accounts_by_id.get(ln.account_id)
            if account is not None:
                row.set_account(account)
                row.load_required_dimensions()
                row.dimension_values = dict(ln.details)
                row._update_dims_complete()
            if ln.currency_id is not None and ln.currency_id != self._base_currency_id:
                row.line_currency_id = ln.currency_id
                row.line_exchange_rate = ln.exchange_rate
            row._update_currency_state()
            row.description_field.set_value(ln.description)
            row.ids.debit_field.text = str(ln.debit) if ln.debit else ""
            row.ids.credit_field.text = str(ln.credit) if ln.credit else ""
        if not lines:
            self.add_line()
            self.add_line()
        self._recalculate()

        temp_no_fa = numerals.to_persian_digits(str(entry.temporary_no))
        self.ids.form_title.text = shape(tr("ویرایش سند «{}»").format(temp_no_fa))
        self.ids.save_button.text = shape(tr("ذخیره تغییرات"))
        self.ids.cancel_edit_button.opacity = 1
        self.ids.cancel_edit_button.disabled = False
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "36dp"
        self._set_status(tr("در حال ویرایش سند شماره‌ی موقت {} — Escape برای لغو.").format(temp_no_fa))
        self.ids.date_field.focus = True
        self.refresh_entries()

    def cancel_edit(self) -> None:
        self._reset_form()
        self._set_status(tr(""))
        self.refresh_entries()

    def confirm_delete(self, journal_entry_id: int) -> None:
        if session.current_company is None:
            return
        entries = je_service.list_journal_entries(session.current_company.company_id)
        entry = next((e for e in entries if e.journal_entry_id == journal_entry_id), None)
        if entry is None:
            return

        if self._delete_dialog is not None:
            self._delete_dialog.dismiss()

        def _do_delete(*_args) -> None:
            self._delete_dialog.dismiss()
            self._perform_delete(journal_entry_id)

        self._delete_dialog = MDDialog(
            title=shape(tr("حذف سند")),
            text=shape(
                tr("سند با شماره‌ی موقت {} حذف شود؟ این کار قابل بازگشت نیست.").format(
                    numerals.to_persian_digits(str(entry.temporary_no))
                )
            ),
            buttons=[
                MDFlatButton(text=shape(tr("لغو")), on_release=lambda *_: self._delete_dialog.dismiss()),
                MDRaisedButton(text=shape(tr("حذف")), md_bg_color=theme.DANGER, on_release=_do_delete),
            ],
        )
        self._delete_dialog.open()

    def _perform_delete(self, journal_entry_id: int) -> None:
        if session.current_company is None:
            return
        try:
            je_service.delete_journal_entry(
                journal_entry_id,
                session.current_company.company_id,
                changed_by_user_id=session.current_user.user_id if session.current_user else None,
            )
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc), is_error=True)
            return
        if self._editing_entry_id == journal_entry_id:
            self._reset_form()
        self._set_status(tr("سند حذف شد."))
        self.refresh_entries()

    def refresh_entries(self) -> None:
        if session.current_company is None:
            self.ids.entries_list.data = []
            return

        entries = je_service.list_journal_entries(session.current_company.company_id)
        self.ids.entries_header.opacity = 1 if entries else 0
        if not entries:
            self.ids.entries_list.data = [
                {"viewclass": "PEmptyState", "icon": "file-document-outline", "text": shape(tr("هنوز سندی ثبت نشده است."))}
            ]
            return

        self.ids.entries_list.data = [
            {
                "journal_entry_id": entry.journal_entry_id,
                "on_edit": self.edit_entry,
                "on_delete": self.confirm_delete,
                "number_text": numerals.to_persian_digits(str(entry.temporary_no)),
                "date_text": numerals.format_jalali_date(entry.document_date),
                "description_text": shape(entry.description or "—"),
                "amount_text": numerals.format_amount(entry.total_amount),
                "status_text": shape(tr(_STATUS_LABELS.get(entry.status_code, entry.status_code))),
                "status_badge_color": _STATUS_COLORS.get(entry.status_code, theme.TEXT_DISABLED),
                "zebra": i % 2 == 1,
                "editable": entry.status_code == "TEMPORARY",
                "selected": entry.journal_entry_id == self._editing_entry_id,
            }
            for i, entry in enumerate(entries)
        ]
