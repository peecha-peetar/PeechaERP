"""صفحه‌ی مدیریت سال‌های مالیِ شرکتِ جاری — هر سالِ مالی با واردکردنِ یک
تاریخِ دلخواه در همان سال ساخته می‌شود (بازه‌ی دقیق طبق الگوی شروع سال مالیِ
شرکت خودکار محاسبه و ۱۲ دوره‌ی ماهانه هم ساخته می‌شود)."""

from __future__ import annotations

import datetime
import os

from kivy.factory import Factory
from kivy.lang import Builder
from kivy.properties import BooleanProperty, NumericProperty, ObjectProperty, StringProperty
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.screen import MDScreen

from peecha import session
from peecha.services import field_labels as field_labels_service
from peecha.services import fiscal_years as fiscal_years_service
from peecha.ui import numerals, theme
from peecha.ui.i18n import tr
from peecha.ui.rtl import shape
from peecha.ui.shortcuts import KeyboardShortcutMixin

_KV_PATH = os.path.join(os.path.dirname(__file__), "fiscal_years.kv")
Builder.load_file(_KV_PATH)


class FiscalYearRowWidget(RecycleDataViewBehavior, MDBoxLayout):
    fiscal_year_id = NumericProperty(0)
    code_text = StringProperty("")
    range_text = StringProperty("")
    periods_text = StringProperty("")
    status_text = StringProperty("")
    is_closed_row = BooleanProperty(False)
    zebra = BooleanProperty(False)
    on_toggle = ObjectProperty(None)

    def toggle(self) -> None:
        if self.on_toggle is not None:
            self.on_toggle(self.fiscal_year_id, not self.is_closed_row)


Factory.register("FiscalYearRowWidget", cls=FiscalYearRowWidget)


class FiscalYearsScreen(KeyboardShortcutMixin, MDScreen):
    def on_pre_enter(self, *args):
        self.ids.on_date_field.text = numerals.format_jalali_date(datetime.date.today())
        self.apply_field_labels()
        self.refresh_list()
        self.bind_shortcuts()

    def on_leave(self, *args):
        self.unbind_shortcuts()

    def apply_field_labels(self) -> None:
        language_id = session.current_language.language_id if session.current_language else None
        labels = {k: tr(v) for k, v in field_labels_service.get_labels_map("fiscal_years", language_id).items()}
        self.ids.on_date_field.hint_text = shape(labels["on_date"])

    def on_shortcut_save(self) -> None:
        self.save_fiscal_year()

    def _set_status(self, message: str, *, is_error: bool = False) -> None:
        self.ids.status_label.text = shape(message)
        self.ids.status_label.text_color = theme.DANGER if is_error else theme.TEXT_SECONDARY

    def refresh_list(self) -> None:
        if session.current_company is None:
            self._set_status(tr("هیچ شرکتی انتخاب نشده است."), is_error=True)
            self.ids.grid_header.opacity = 0
            self.ids.years_list.data = []
            return

        rows = fiscal_years_service.list_fiscal_years(session.current_company.company_id)
        self.ids.grid_header.opacity = 1 if rows else 0
        if not rows:
            self.ids.years_list.data = [
                {"viewclass": "PEmptyState", "icon": "calendar-blank-outline", "text": shape(tr("هنوز سالِ مالی‌ای تعریف نشده است."))}
            ]
            return

        self.ids.years_list.data = [
            {
                "fiscal_year_id": row.fiscal_year_id,
                "on_toggle": self._toggle_closed,
                "code_text": numerals.to_persian_digits(row.code),
                "range_text": shape(
                    f"{numerals.format_jalali_date(row.start_date)} تا "
                    f"{numerals.format_jalali_date(row.end_date)}"
                ),
                "periods_text": numerals.to_persian_digits(f"{row.period_count} دوره"),
                "status_text": shape(tr("بسته") if row.is_closed else tr("باز")),
                "is_closed_row": row.is_closed,
                "zebra": i % 2 == 1,
            }
            for i, row in enumerate(rows)
        ]

    def save_fiscal_year(self) -> None:
        if session.current_company is None:
            self._set_status(tr("هیچ شرکتی انتخاب نشده است."), is_error=True)
            return
        try:
            on_date = numerals.parse_jalali_date(self.ids.on_date_field.text)
        except ValueError as exc:
            self._set_status(str(exc), is_error=True)
            return
        try:
            fiscal_year = fiscal_years_service.create_fiscal_year_for_date(
                company_id=session.current_company.company_id,
                start_month=session.current_company.fiscal_year_start_month,
                start_day=session.current_company.fiscal_year_start_day,
                on_date=on_date,
            )
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc), is_error=True)
            return
        self._set_status(f"سالِ مالیِ «{numerals.to_persian_digits(fiscal_year.code)}» ساخته شد.")
        self.refresh_list()

    def _toggle_closed(self, fiscal_year_id: int, is_closed: bool) -> None:
        if session.current_company is None:
            return
        try:
            fiscal_years_service.set_closed(fiscal_year_id, session.current_company.company_id, is_closed)
        except Exception as exc:  # noqa: BLE001
            self._set_status(tr("خطا: {}").format(exc), is_error=True)
            return
        self.refresh_list()
