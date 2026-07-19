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
from kivy.properties import BooleanProperty, ListProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen

from peecha import session
from peecha.services import chart_of_accounts as coa_service
from peecha.services import journal_entries as je_service
from peecha.ui import numerals, theme
from peecha.ui.rtl import shape
from peecha.ui.shortcuts import KeyboardShortcutMixin

_KV_PATH = os.path.join(os.path.dirname(__file__), "journal_entry.kv")
Builder.load_file(_KV_PATH)

_STATUS_LABELS = {"TEMPORARY": "موقت", "PERMANENT": "دائم", "REVERSED": "برگشت‌خورده", "CANCELLED": "ابطال‌شده"}
_STATUS_COLORS = {
    "TEMPORARY": theme.WARNING,
    "PERMANENT": theme.SUCCESS,
    "REVERSED": theme.DANGER,
    "CANCELLED": theme.TEXT_DISABLED,
}


class JournalEntryLineRow(MDBoxLayout):
    def __init__(self, account_options, on_change, on_remove, on_validate, **kwargs):
        super().__init__(**kwargs)
        self._account_options = account_options
        self._on_change = on_change
        self._on_remove = on_remove
        self._on_validate = on_validate
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

    def set_account(self, account_id: int, label: str) -> None:
        self.account_id = account_id
        self.ids.account_button.text = shape(label)

    def _select_account(self, account_id: int, label: str) -> None:
        if self._menu is not None:
            self._menu.dismiss()
        self.set_account(account_id, label)
        self._on_change()

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
        self.ids.description_field.focus_next = self._rows[0].ids.account_button
        for i, row in enumerate(self._rows):
            if i + 1 < len(self._rows):
                row.ids.credit_field.focus_next = self._rows[i + 1].ids.account_button
                self._rows[i + 1].ids.account_button.focus_previous = row.ids.credit_field
            else:
                row.ids.credit_field.focus_next = self.ids.add_line_button

    def _focus_after_row(self, row: JournalEntryLineRow) -> None:
        """Enter در فیلد بدهکار/بستانکارِ آخرین ردیف: ردیف جدید اضافه و
        فوکوس به آن منتقل می‌شود (مثل صفحه‌گسترده) — Enter در بقیه‌ی
        ردیف‌ها فقط به ردیف بعدی می‌رود."""
        if row is self._rows[-1]:
            self.add_line()
            self._rows[-1].ids.account_button.focus = True
        else:
            idx = self._rows.index(row)
            self._rows[idx + 1].ids.account_button.focus = True

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
                message = f"سند با شماره‌ی موقت {result.temporary_no} ثبت شد."
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
                row.set_account(account.account_id, f"{account.full_code} — {account.name}")
            row.ids.description_field.text = ln.description
            row.ids.debit_field.text = str(ln.debit) if ln.debit else ""
            row.ids.credit_field.text = str(ln.credit) if ln.credit else ""
        if not lines:
            self.add_line()
            self.add_line()
        self._recalculate()

        self.ids.form_title.text = shape(f"ویرایش سند «{entry.temporary_no}»")
        self.ids.save_button.text = shape("ذخیره تغییرات")
        self.ids.cancel_edit_button.opacity = 1
        self.ids.cancel_edit_button.disabled = False
        self.ids.cancel_edit_button.size_hint_y = None
        self.ids.cancel_edit_button.height = "36dp"
        self._set_status(f"در حال ویرایش سند شماره‌ی موقت {entry.temporary_no} — Escape برای لغو.")
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
            text=shape(f"سند با شماره‌ی موقت {entry.temporary_no} حذف شود؟ این کار قابل بازگشت نیست."),
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
                    number_text=str(entry.temporary_no),
                    date_text=numerals.format_jalali_date(entry.document_date),
                    description_text=shape(entry.description or "—"),
                    amount_text=f"{entry.total_amount:,}",
                    status_text=shape(_STATUS_LABELS.get(entry.status_code, entry.status_code)),
                    status_badge_color=_STATUS_COLORS.get(entry.status_code, theme.TEXT_DISABLED),
                    zebra=i % 2 == 1,
                    editable=entry.status_code == "TEMPORARY",
                    selected=entry.journal_entry_id == self._editing_entry_id,
                )
            )

    def go_to_chart_of_accounts(self) -> None:
        self.manager.current = "chart_of_accounts"
