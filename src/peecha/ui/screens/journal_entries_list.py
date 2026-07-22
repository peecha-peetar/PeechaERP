"""صفحه‌ی فهرستِ اسناد حسابداری: طبق درخواستِ صریح، این فهرست از فرمِ صدور
سند جدا شده تا وقتی تعدادِ اسناد زیاد می‌شود همچنان قابلِ‌مرور/جستجو بماند
(نه یک فهرستِ کوچکِ کنارِ فرم که با اسکرول/بدونِ جستجو گم می‌شود).

کلیک روی هر ردیف (فقط برای سندهای TEMPORARY/DRAFT) کاربر را به صفحه‌ی
صدور سند می‌برد و همان‌جا edit_entry() را صدا می‌زند."""

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
from kivymd.uix.screen import MDScreen

from peecha import session
from peecha.services import journal_entries as je_service
from peecha.ui import numerals, theme
from peecha.ui.i18n import tr
from peecha.ui.rtl import shape

_KV_PATH = os.path.join(os.path.dirname(__file__), "journal_entries_list.kv")
Builder.load_file(_KV_PATH)

_STATUS_LABELS = {
    "DRAFT": "پیش‌نویس",
    "TEMPORARY": "موقت",
    "PERMANENT": "دائم",
    "REVERSED": "برگشت‌خورده",
    "CANCELLED": "ابطال‌شده",
}
_STATUS_COLORS = {
    "DRAFT": theme.TEXT_DISABLED,
    "TEMPORARY": theme.WARNING,
    "PERMANENT": theme.SUCCESS,
    "REVERSED": theme.DANGER,
    "CANCELLED": theme.TEXT_DISABLED,
}


class JournalEntryRowWidget(RecycleDataViewBehavior, ButtonBehavior, MDBoxLayout):
    """یک ردیفِ جدولِ اسناد.

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
    on_edit = ObjectProperty(None)
    on_delete = ObjectProperty(None)

    def on_release(self) -> None:
        if self.editable and self.on_edit is not None:
            self.on_edit(self.journal_entry_id)

    def request_delete(self) -> None:
        if self.editable and self.on_delete is not None:
            self.on_delete(self.journal_entry_id)


Factory.register("JournalEntryRowWidget", cls=JournalEntryRowWidget)


class JournalEntriesListScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._entries: list[je_service.JournalEntrySummary] = []
        self._delete_dialog: MDDialog | None = None

    def on_pre_enter(self, *args):
        self.refresh_list()

    def refresh_list(self) -> None:
        if session.current_company is None:
            self._entries = []
        else:
            self._entries = je_service.list_journal_entries(session.current_company.company_id)
        self._apply_filter()

    def filter_entries(self) -> None:
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = numerals.to_ascii_digits(self.ids.search_field.text).strip()
        if not query:
            filtered = self._entries
        else:
            filtered = [
                e
                for e in self._entries
                if query in str(e.temporary_no)
                or query in (e.alternative_number or "")
                or query in (e.description or "")
            ]

        self.ids.status_label.text_color = theme.TEXT_SECONDARY
        self.ids.status_label.text = (
            "" if not self._entries else shape(tr("{} سند").format(numerals.to_persian_digits(str(len(filtered)))))
        )

        if not filtered:
            self.ids.entries_list.data = [
                {
                    "viewclass": "PEmptyState",
                    "icon": "file-document-outline",
                    "text": shape(tr("سندی یافت نشد.") if self._entries else tr("هنوز سندی ثبت نشده است.")),
                }
            ]
            return

        self.ids.entries_list.data = [
            {
                "journal_entry_id": entry.journal_entry_id,
                "on_edit": self.open_entry,
                "on_delete": self.confirm_delete,
                "number_text": numerals.to_persian_digits(str(entry.temporary_no)),
                "date_text": numerals.format_jalali_date(entry.document_date),
                "description_text": shape(entry.description or "—"),
                "amount_text": numerals.format_amount(entry.total_amount),
                "status_text": shape(tr(_STATUS_LABELS.get(entry.status_code, entry.status_code))),
                "status_badge_color": _STATUS_COLORS.get(entry.status_code, theme.TEXT_DISABLED),
                "zebra": i % 2 == 1,
                "editable": entry.status_code in ("TEMPORARY", "DRAFT"),
            }
            for i, entry in enumerate(filtered)
        ]

    def open_new_entry(self) -> None:
        from kivymd.app import MDApp  # noqa: PLC0415

        shell = MDApp.get_running_app().root.get_screen("shell")
        shell.open_screen("GL_JE", then=lambda screen: screen.cancel_edit())

    def open_entry(self, journal_entry_id: int) -> None:
        from kivymd.app import MDApp  # noqa: PLC0415

        shell = MDApp.get_running_app().root.get_screen("shell")
        shell.open_screen("GL_JE", then=lambda screen: screen.edit_entry(journal_entry_id))

    def confirm_delete(self, journal_entry_id: int) -> None:
        if session.current_company is None:
            return
        entry = next((e for e in self._entries if e.journal_entry_id == journal_entry_id), None)
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
        except Exception as exc:  # noqa: BLE001 - نمایشِ هر خطای اعتبارسنجی/دیتابیس به کاربر
            self.ids.status_label.text_color = theme.DANGER
            self.ids.status_label.text = shape(tr("خطا: {}").format(exc))
            return
        self.refresh_list()
