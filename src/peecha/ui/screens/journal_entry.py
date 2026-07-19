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

from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.dropdown import DropDown
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.screen import MDScreen

from peecha import session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import journal_entries as je_service
from peecha.ui import numerals, theme
from peecha.ui.rtl import shape
from peecha.ui.shortcuts import KeyboardShortcutMixin
from peecha.ui.widgets import PTextField

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
        kwargs.setdefault("hint_text", shape("جستجوی کد یا نام حساب"))
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


class JournalEntryLineRow(MDBoxLayout):
    def __init__(self, account_options, on_change, on_remove, on_validate, **kwargs):
        super().__init__(**kwargs)
        self._on_change = on_change
        self._on_remove = on_remove
        self._on_validate = on_validate
        self.account_field = AccountSearchField(account_options=account_options, on_select=self._account_selected)
        self.ids.account_slot.add_widget(self.account_field)
        self.account_field.focus_next = self.ids.description_field
        self.ids.description_field.focus_previous = self.account_field

    @property
    def account_id(self) -> int | None:
        return self.account_field.account_id

    def set_account(self, account_row: coa_service.AccountRow) -> None:
        self.account_field.set_selected(account_row)

    def _account_selected(self) -> None:
        self._on_change()
        self.ids.debit_field.focus = True

    def on_debit_changed(self) -> None:
        if self.ids.debit_field.text.strip():
            self.ids.credit_field.text = ""
        self._on_change()

    def on_credit_changed(self) -> None:
        if self.ids.credit_field.text.strip():
            self.ids.debit_field.text = ""
        self._on_change()

    def request_next(self) -> None:
        self._on_validate(self)

    def remove_line(self) -> None:
        self._on_remove(self)


class JournalEntryRowWidget(ButtonBehavior, MDBoxLayout):
    """یک ردیفِ جدولِ «اسناد اخیر»: کلیک روی ردیف = بارگذاری برای ویرایش."""

    number_text = StringProperty("")
    date_text = StringProperty("")
    description_text = StringProperty("")
    amount_text = StringProperty("")
    status_text = StringProperty("")
    status_badge_color = ListProperty([0, 0, 0, 1])
    zebra = BooleanProperty(False)
    editable = BooleanProperty(False)
    selected = BooleanProperty(False)

    def __init__(self, journal_entry_id: int, on_edit, on_delete, **kwargs):
        super().__init__(**kwargs)
        self.journal_entry_id = journal_entry_id
        self._on_edit = on_edit
        self._on_delete = on_delete

    def on_release(self) -> None:
        if self.editable:
            self._on_edit(self.journal_entry_id)

    def request_delete(self) -> None:
        if self.editable:
            self._on_delete(self.journal_entry_id)


class JournalEntryScreen(KeyboardShortcutMixin, MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._account_options: list[coa_service.AccountRow] = []
        self._rows: list[JournalEntryLineRow] = []
        self._editing_entry_id: int | None = None
        self._delete_dialog: MDDialog | None = None

    def on_pre_enter(self, *args):
        self._load_accounts()
        self._reset_form()
        self._set_status("")
        self.refresh_entries()
        self.bind_shortcuts()

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
        else:
            self._account_options = coa_service.list_postable_accounts(session.current_company.company_id)

    def _reset_form(self) -> None:
        # توجه: پیام وضعیت (مثلاً «سند ثبت شد») را عمداً اینجا پاک نمی‌کنیم؛
        # save_entry() بعد از ثبت موفق همین متد را صدا می‌زند تا فرم برای سند
        # بعدی خالی شود، اما پیام موفقیت باید روی صفحه باقی بماند.
        self._editing_entry_id = None
        self.ids.lines_box.clear_widgets()
        self._rows = []
        self.ids.date_field.text = numerals.format_jalali_date(datetime.date.today())
        self.ids.description_field.text = ""
        self.ids.form_title.text = shape("صدور سند حسابداری")
        self.ids.save_button.text = shape("ثبت سند")
        self.ids.cancel_edit_button.opacity = 0
        self.ids.cancel_edit_button.disabled = True
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "0dp"
        self.add_line()
        self.add_line()
        self._recalculate()
        # طبق درخواستِ صریح: وقتی فرمِ سند بارگذاری می‌شود، فوکوس روی
        # فیلدِ جستجوی کدِ حسابِ ردیفِ اول باشد.
        self._rows[0].account_field.focus = True

    def add_line(self) -> None:
        row = JournalEntryLineRow(
            account_options=self._account_options,
            on_change=self._recalculate,
            on_remove=self._remove_line,
            on_validate=self._focus_after_row,
        )
        self._rows.append(row)
        self.ids.lines_box.add_widget(row)
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

        self.ids.total_debit_label.text = shape(f"جمع بدهکار: {numerals.format_amount(total_debit)}")
        self.ids.total_credit_label.text = shape(f"جمع بستانکار: {numerals.format_amount(total_credit)}")

        balanced = total_debit == total_credit and total_debit > 0
        chip_color = theme.SUCCESS if balanced else theme.DANGER
        self.ids.balance_label.text = shape("متعادل" if balanced else "نامتعادل")
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
                    description=row.ids.description_field.text.strip(),
                    debit=debit,
                    credit=credit,
                )
            )
        return lines

    def save_entry(self) -> None:
        if session.current_company is None or session.current_user is None:
            self._set_status("کاربر یا شرکت جاری نامعتبر است.", is_error=True)
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
                    description=self.ids.description_field.text.strip(),
                    lines=lines,
                )
                message = "سند به‌روزرسانی شد."
            else:
                result = je_service.create_journal_entry(
                    company_id=session.current_company.company_id,
                    created_by_user_id=session.current_user.user_id,
                    document_date=document_date,
                    description=self.ids.description_field.text.strip(),
                    lines=lines,
                )
                message = f"سند با شماره‌ی موقت {numerals.to_persian_digits(str(result.temporary_no))} ثبت شد."
        except Exception as exc:  # noqa: BLE001 - نمایش هر خطای اعتبارسنجی/دیتابیس به کاربر
            self._set_status(f"خطا: {exc}", is_error=True)
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
            self._set_status(f"خطا: {exc}", is_error=True)
            return

        entries = je_service.list_journal_entries(session.current_company.company_id)
        entry = next((e for e in entries if e.journal_entry_id == journal_entry_id), None)
        if entry is None:
            return

        self._editing_entry_id = journal_entry_id
        self.ids.lines_box.clear_widgets()
        self._rows = []
        self.ids.date_field.text = numerals.format_jalali_date(entry.document_date)
        self.ids.description_field.text = entry.description
        accounts_by_id = {a.account_id: a for a in self._account_options}
        for ln in lines:
            self.add_line()
            row = self._rows[-1]
            account = accounts_by_id.get(ln.account_id)
            if account is not None:
                row.set_account(account)
            row.ids.description_field.text = ln.description
            row.ids.debit_field.text = str(ln.debit) if ln.debit else ""
            row.ids.credit_field.text = str(ln.credit) if ln.credit else ""
        if not lines:
            self.add_line()
            self.add_line()
        self._recalculate()

        temp_no_fa = numerals.to_persian_digits(str(entry.temporary_no))
        self.ids.form_title.text = shape(f"ویرایش سند «{temp_no_fa}»")
        self.ids.save_button.text = shape("ذخیره تغییرات")
        self.ids.cancel_edit_button.opacity = 1
        self.ids.cancel_edit_button.disabled = False
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "36dp"
        self._set_status(f"در حال ویرایش سند شماره‌ی موقت {temp_no_fa} — Escape برای لغو.")
        self.ids.date_field.focus = True
        self.refresh_entries()

    def cancel_edit(self) -> None:
        self._reset_form()
        self._set_status("")
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
            title=shape("حذف سند"),
            text=shape(
                f"سند با شماره‌ی موقت {numerals.to_persian_digits(str(entry.temporary_no))} حذف شود؟ "
                "این کار قابل بازگشت نیست."
            ),
            buttons=[
                MDFlatButton(text=shape("لغو"), on_release=lambda *_: self._delete_dialog.dismiss()),
                MDRaisedButton(text=shape("حذف"), md_bg_color=theme.DANGER, on_release=_do_delete),
            ],
        )
        self._delete_dialog.open()

    def _perform_delete(self, journal_entry_id: int) -> None:
        if session.current_company is None:
            return
        try:
            je_service.delete_journal_entry(journal_entry_id, session.current_company.company_id)
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"خطا: {exc}", is_error=True)
            return
        if self._editing_entry_id == journal_entry_id:
            self._reset_form()
        self._set_status("سند حذف شد.")
        self.refresh_entries()

    def refresh_entries(self) -> None:
        self.ids.entries_list.clear_widgets()
        if session.current_company is None:
            return

        from peecha.ui.widgets import PEmptyState  # noqa: PLC0415

        entries = je_service.list_journal_entries(session.current_company.company_id)
        self.ids.entries_header.opacity = 1 if entries else 0
        if not entries:
            self.ids.entries_list.add_widget(
                PEmptyState(icon="file-document-outline", text=shape("هنوز سندی ثبت نشده است."))
            )
            return

        for i, entry in enumerate(entries):
            self.ids.entries_list.add_widget(
                JournalEntryRowWidget(
                    journal_entry_id=entry.journal_entry_id,
                    on_edit=self.edit_entry,
                    on_delete=self.confirm_delete,
                    number_text=numerals.to_persian_digits(str(entry.temporary_no)),
                    date_text=numerals.format_jalali_date(entry.document_date),
                    description_text=shape(entry.description or "—"),
                    amount_text=numerals.format_amount(entry.total_amount),
                    status_text=shape(_STATUS_LABELS.get(entry.status_code, entry.status_code)),
                    status_badge_color=_STATUS_COLORS.get(entry.status_code, theme.TEXT_DISABLED),
                    zebra=i % 2 == 1,
                    editable=entry.status_code == "TEMPORARY",
                    selected=entry.journal_entry_id == self._editing_entry_id,
                )
            )
