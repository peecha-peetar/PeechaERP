"""صفحه‌ی صدور سند حسابداری: هدر سند + ردیف‌های بدهکار/بستانکار پویا.

هر ردیف یک JournalEntryLineRow است (تعریف در همین فایل، نه widgets.py،
چون فقط همین صفحه از آن استفاده می‌کند). موازنه‌ی بدهکار/بستانکار به‌صورت
زنده با هر تغییرِ مبلغ محاسبه می‌شود؛ اعتبارسنجیِ نهایی (شامل قابل‌ثبت‌بودنِ
حساب و برابریِ دقیق مبالغ) در services/journal_entries.py انجام می‌شود.
"""

from __future__ import annotations

import datetime
import decimal
import os

from kivy.lang import Builder
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen

from peecha import session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import journal_entries as je_service
from peecha.ui import numerals, theme
from peecha.ui.rtl import shape

_KV_PATH = os.path.join(os.path.dirname(__file__), "journal_entry.kv")
Builder.load_file(_KV_PATH)


class JournalEntryLineRow(MDBoxLayout):
    def __init__(self, account_options, on_change, on_remove, **kwargs):
        super().__init__(**kwargs)
        self._account_options = account_options
        self._on_change = on_change
        self._on_remove = on_remove
        self._menu: MDDropdownMenu | None = None
        self.account_id: int | None = None

    def open_account_menu(self) -> None:
        items = [
            {
                "text": shape(f"{row.full_code} — {row.name}"),
                "on_release": lambda account_id=row.account_id, label=f"{row.full_code} — {row.name}": (
                    self._select_account(account_id, label)
                ),
            }
            for row in self._account_options
        ]
        if not items:
            items = [{"text": shape("هیچ حساب قابل‌ثبتی تعریف نشده"), "on_release": lambda: self._menu.dismiss()}]
        self._menu = MDDropdownMenu(caller=self.ids.account_button, items=items, width_mult=4)
        self._menu.open()

    def _select_account(self, account_id: int, label: str) -> None:
        if self._menu is not None:
            self._menu.dismiss()
        self.account_id = account_id
        self.ids.account_button.text = shape(label)
        self._on_change()

    def on_debit_changed(self) -> None:
        if self.ids.debit_field.text.strip():
            self.ids.credit_field.text = ""
        self._on_change()

    def on_credit_changed(self) -> None:
        if self.ids.credit_field.text.strip():
            self.ids.debit_field.text = ""
        self._on_change()

    def remove_line(self) -> None:
        self._on_remove(self)


class JournalEntryScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._account_options: list[coa_service.AccountRow] = []
        self._rows: list[JournalEntryLineRow] = []

    def on_pre_enter(self, *args):
        self._load_accounts()
        self._reset_form()
        self._set_status("")

    def _load_accounts(self) -> None:
        if session.current_company is None:
            self._account_options = []
        else:
            self._account_options = coa_service.list_postable_accounts(session.current_company.company_id)

    def _reset_form(self) -> None:
        # توجه: پیام وضعیت (مثلاً «سند ثبت شد») را عمداً اینجا پاک نمی‌کنیم؛
        # submit() بعد از ثبت موفق همین متد را صدا می‌زند تا فرم برای سند
        # بعدی خالی شود، اما پیام موفقیت باید روی صفحه باقی بماند.
        self.ids.lines_box.clear_widgets()
        self._rows = []
        self.ids.date_field.text = numerals.format_jalali_date(datetime.date.today())
        self.ids.description_field.text = ""
        self.add_line()
        self.add_line()
        self._recalculate()

    def add_line(self) -> None:
        row = JournalEntryLineRow(
            account_options=self._account_options, on_change=self._recalculate, on_remove=self._remove_line
        )
        self._rows.append(row)
        self.ids.lines_box.add_widget(row)

    def _remove_line(self, row: JournalEntryLineRow) -> None:
        if row in self._rows:
            self._rows.remove(row)
            self.ids.lines_box.remove_widget(row)
            self._recalculate()

    def _recalculate(self) -> None:
        total_debit = decimal.Decimal(0)
        total_credit = decimal.Decimal(0)
        for row in self._rows:
            try:
                total_debit += numerals.parse_decimal(row.ids.debit_field.text)
                total_credit += numerals.parse_decimal(row.ids.credit_field.text)
            except ValueError:
                pass  # حین تایپ مقدار ناقص عادی است؛ فقط در ثبت نهایی خطا نشان داده می‌شود

        self.ids.total_debit_label.text = shape(f"جمع بدهکار: {total_debit:,}")
        self.ids.total_credit_label.text = shape(f"جمع بستانکار: {total_credit:,}")

        balanced = total_debit == total_credit and total_debit > 0
        chip_color = theme.SUCCESS if balanced else theme.DANGER
        self.ids.balance_label.text = shape("متعادل" if balanced else "نامتعادل")
        self.ids.balance_label.text_color = chip_color
        self.ids.balance_chip.md_bg_color = (chip_color[0], chip_color[1], chip_color[2], 0.12)

    def _set_status(self, message: str, *, is_error: bool = False) -> None:
        self.ids.status_label.text = shape(message)
        self.ids.status_label.text_color = theme.DANGER if is_error else theme.TEXT_SECONDARY

    def submit(self) -> None:
        if session.current_company is None or session.current_user is None:
            self._set_status("کاربر یا شرکت جاری نامعتبر است.", is_error=True)
            return

        try:
            document_date = numerals.parse_jalali_date(self.ids.date_field.text)
        except ValueError as exc:
            self._set_status(str(exc), is_error=True)
            return

        lines: list[je_service.LineInput] = []
        for row in self._rows:
            if row.account_id is None:
                continue
            try:
                debit = numerals.parse_decimal(row.ids.debit_field.text)
                credit = numerals.parse_decimal(row.ids.credit_field.text)
            except ValueError as exc:
                self._set_status(str(exc), is_error=True)
                return
            lines.append(
                je_service.LineInput(
                    account_id=row.account_id,
                    description=row.ids.description_field.text.strip(),
                    debit=debit,
                    credit=credit,
                )
            )

        try:
            result = je_service.create_journal_entry(
                company_id=session.current_company.company_id,
                created_by_user_id=session.current_user.user_id,
                document_date=document_date,
                description=self.ids.description_field.text.strip(),
                lines=lines,
            )
        except Exception as exc:  # noqa: BLE001 - نمایش هر خطای اعتبارسنجی/دیتابیس به کاربر
            self._set_status(f"خطا: {exc}", is_error=True)
            return

        self._set_status(f"سند با شماره‌ی موقت {result.temporary_no} ثبت شد.")
        self._reset_form()

    def go_to_chart_of_accounts(self) -> None:
        self.manager.current = "chart_of_accounts"
